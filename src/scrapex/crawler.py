"""Async crawl engine."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import mimetypes
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from scrapex.config import ScrapeConfig
from scrapex.extract import extract
from scrapex.models import PageResult
from scrapex.urls import is_same_site, looks_like_page, normalize_url, site_key

log = logging.getLogger("scrapex")

MAX_BODY_BYTES = 15 * 1024 * 1024
MAX_SITEMAP_URLS = 5000
RETRY_STATUSES = {429, 500, 502, 503, 504}
LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", re.I | re.S)


@dataclass
class CrawlStats:
    queued: int = 0
    fetched: int = 0
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    duplicates: int = 0
    bytes: int = 0
    images_downloaded: int = 0
    started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def pages_per_sec(self) -> float:
        return self.fetched / self.elapsed if self.elapsed > 0 else 0.0


@dataclass
class CrawlReport:
    config: ScrapeConfig
    pages: list[PageResult]
    stats: CrawlStats
    run_dir: Path
    started_at: str
    finished_at: str = ""
    stopped: bool = False


@dataclass
class CrawlEvent:
    kind: str  # "log" | "page" | "progress"
    message: str = ""
    level: int = logging.INFO
    page: PageResult | None = None
    stats: CrawlStats | None = None


EventHandler = Callable[[CrawlEvent], None]


class Crawler:
    def __init__(self, config: ScrapeConfig, on_event: EventHandler | None = None) -> None:
        self.config = config
        self.on_event = on_event or (lambda e: None)
        self.stats = CrawlStats()
        self.pages: list[PageResult] = []
        self._seen: set[str] = set()
        self._queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._budget = 0
        self._stop = False
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_next: dict[str, float] = {}
        self._host_delay: dict[str, float] = {}
        self._content_hashes: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None
        self._renderer = None
        self.run_dir = self._make_run_dir()

    # ---------------------------------------------------------------- public

    def stop(self) -> None:
        self._stop = True
        self._emit_log("Stop requested - finishing in-flight requests…", logging.WARNING)

    async def run(self) -> CrawlReport:
        cfg = self.config
        started_at = _now()
        self._attach_file_log()
        self._emit_log(f"Starting crawl of {cfg.url} → {self.run_dir}")

        async with httpx.AsyncClient(
            headers={"User-Agent": cfg.user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                     "Accept-Language": "en-US,en;q=0.8"},
            timeout=cfg.timeout,
            follow_redirects=True,
            proxy=cfg.proxy,
            limits=httpx.Limits(max_connections=cfg.concurrency * 2, max_keepalive_connections=cfg.concurrency),
            http2=_has_h2(),
        ) as client:
            self._client = client
            if cfg.render_js:
                from scrapex.render import Renderer
                self._renderer = Renderer(cfg)
                await self._renderer.start()
            try:
                await self._enqueue(cfg.url, 0, force=True)
                if cfg.use_sitemap:
                    await self._seed_from_sitemaps()
                workers = [asyncio.create_task(self._worker()) for _ in range(cfg.concurrency)]
                await self._queue.join()
                for w in workers:
                    w.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                if cfg.download_images and not self._stop:
                    await self._download_images()
            finally:
                if self._renderer:
                    await self._renderer.close()
                self._emit_log(
                    f"Done: {self.stats.ok} ok, {self.stats.failed} failed, {self.stats.skipped} skipped "
                    f"in {self.stats.elapsed:.1f}s ({self.stats.pages_per_sec:.2f} pages/s)"
                )
                self._emit_progress()
                self._detach_file_log()
        self.pages.sort(key=lambda p: (p.depth, p.url))
        return CrawlReport(cfg, self.pages, self.stats, self.run_dir, started_at, _now(), self._stop)

    # --------------------------------------------------------------- queueing

    async def _enqueue(self, url: str, depth: int, force: bool = False) -> None:
        norm = normalize_url(url)
        if norm is None or norm in self._seen:
            return
        if not force:
            if depth > self.config.max_depth or not looks_like_page(norm) or not self._passes_filters(norm):
                return
            if self.config.same_domain and not is_same_site(norm, self.config.url):
                return
        self._seen.add(norm)
        self.stats.queued += 1
        await self._queue.put((norm, depth))

    def _passes_filters(self, url: str) -> bool:
        cfg = self.config
        if cfg.include_patterns and not any(_match(url, p) for p in cfg.include_patterns):
            return False
        return not any(_match(url, p) for p in cfg.exclude_patterns)

    async def _seed_from_sitemaps(self) -> None:
        root = self.config.url
        origin = f"{urlparse(root).scheme}://{urlparse(root).netloc}"
        candidates = [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
        robots = await self._get_robots(root)
        if robots and robots.site_maps():
            candidates = list(robots.site_maps()) + candidates

        found: list[str] = []
        visited: set[str] = set()
        while candidates and len(found) < MAX_SITEMAP_URLS and len(visited) < 25:
            sm = candidates.pop(0)
            if sm in visited:
                continue
            visited.add(sm)
            try:
                resp = await self._client.get(sm)
                if resp.status_code != 200:
                    continue
                body = resp.text
            except httpx.HTTPError:
                continue
            for loc in LOC_RE.findall(body):
                if loc.lower().endswith((".xml", ".xml.gz")) and "<sitemapindex" in body.lower():
                    candidates.append(loc)
                else:
                    found.append(loc)
        before = self.stats.queued
        for url in found[:MAX_SITEMAP_URLS]:
            await self._enqueue(url, 1)
        if found:
            self._emit_log(f"Sitemap: discovered {len(found)} URLs, queued {self.stats.queued - before}")

    # ---------------------------------------------------------------- workers

    async def _worker(self) -> None:
        while True:
            url, depth = await self._queue.get()
            try:
                if self._stop or self._budget >= self.config.max_pages:
                    continue
                if self.config.respect_robots and not await self._allowed(url):
                    self.stats.skipped += 1
                    self._emit_log(f"robots.txt disallows {url}", logging.DEBUG)
                    continue
                self._budget += 1
                page = await self._process(url, depth)
                if page is None:  # not HTML: give the budget back
                    self._budget -= 1
                    self.stats.skipped += 1
                    continue
                self.pages.append(page)
                self.on_event(CrawlEvent("page", page=page, stats=self.stats))
                if page.ok and depth < self.config.max_depth and not page.duplicate_of:
                    for link in page.internal_links if self.config.same_domain else page.internal_links + page.external_links:
                        await self._enqueue(link["url"], depth + 1)
            except Exception as exc:  # never let one URL kill a worker
                log.exception("Worker error on %s", url)
                self._emit_log(f"Unexpected error on {url}: {exc}", logging.ERROR)
            finally:
                self._emit_progress()
                self._queue.task_done()

    async def _process(self, url: str, depth: int) -> PageResult | None:
        page = PageResult(url=url, depth=depth, fetched_at=_now())
        t0 = time.monotonic()
        try:
            if self._renderer:
                await self._throttle(url)
                status, final_url, ctype, html = await self._renderer.fetch(url)
            else:
                status, final_url, ctype, html = await self._fetch(url)
        except Exception as exc:
            page.error = f"{type(exc).__name__}: {exc}"
            page.elapsed_ms = int((time.monotonic() - t0) * 1000)
            self.stats.fetched += 1
            self.stats.failed += 1
            self._emit_log(f"✗ {url} - {page.error}", logging.WARNING)
            return page

        page.elapsed_ms = int((time.monotonic() - t0) * 1000)
        page.status, page.final_url, page.content_type = status, final_url, ctype
        if html is None:
            return None
        self.stats.fetched += 1
        self.stats.bytes += len(html.encode("utf-8", "ignore"))

        if status >= 400:
            page.error = f"HTTP {status}"
            self.stats.failed += 1
            self._emit_log(f"✗ {url} - HTTP {status}", logging.WARNING)
            return page

        # Redirects can lead off-site or onto an already-crawled URL.
        final_norm = normalize_url(final_url)
        if final_norm and final_norm != url:
            if self.config.same_domain and not is_same_site(final_norm, self.config.url):
                page.error = f"Redirected off-site to {final_url}"
                self.stats.skipped += 1
                return page
            self._seen.add(final_norm)

        await asyncio.to_thread(extract, html, page, self.config.url, self.config.selectors)

        digest = hashlib.sha1(page.text.encode("utf-8", "ignore")).hexdigest()
        if page.text and digest in self._content_hashes:
            page.duplicate_of = self._content_hashes[digest]
            self.stats.duplicates += 1
        else:
            self._content_hashes[digest] = url
        self.stats.ok += 1
        self._emit_log(f"✓ [{status}] {url} ({page.word_count} words, {page.elapsed_ms} ms)")
        return page

    async def _fetch(self, url: str) -> tuple[int, str, str, str | None]:
        """Returns (status, final_url, content_type, html-or-None-if-not-html)."""
        attempt = 0
        while True:
            await self._throttle(url)
            try:
                async with self._client.stream("GET", url) as resp:
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                    if resp.status_code in RETRY_STATUSES and attempt < self.config.retries:
                        wait = _retry_after(resp.headers.get("retry-after")) or (2 ** attempt)
                        attempt += 1
                        self._emit_log(f"HTTP {resp.status_code} on {url}, retry {attempt} in {wait:.1f}s", logging.WARNING)
                        self._slow_down(url, wait)
                        await asyncio.sleep(wait)
                        continue
                    if ctype and "html" not in ctype and "xml" not in ctype and not ctype.startswith("text/"):
                        return resp.status_code, str(resp.url), ctype, None
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY_BYTES:
                            break
                    return resp.status_code, str(resp.url), ctype, _decode(bytes(body), resp.charset_encoding)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                if attempt >= self.config.retries:
                    raise
                attempt += 1
                await asyncio.sleep(2 ** attempt)

    # --------------------------------------------------------- politeness

    async def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            wait = self._host_next.get(host, 0) - now
            if wait > 0:
                await asyncio.sleep(wait)
            delay = max(self.config.delay, self._host_delay.get(host, 0))
            self._host_next[host] = time.monotonic() + delay

    def _slow_down(self, url: str, seconds: float) -> None:
        """Adaptive back-off: after a 429/5xx, space requests to this host further apart."""
        host = urlparse(url).netloc
        self._host_delay[host] = min(max(self._host_delay.get(host, self.config.delay) * 2, seconds / 2), 30)

    async def _get_robots(self, url: str) -> RobotFileParser | None:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        async with self._robots_lock:
            if origin in self._robots:
                return self._robots[origin]
            parser: RobotFileParser | None = None
            try:
                resp = await self._client.get(origin + "/robots.txt")
                if resp.status_code == 200:
                    parser = RobotFileParser()
                    parser.parse(resp.text.splitlines())
                    crawl_delay = parser.crawl_delay(self.config.user_agent) or parser.crawl_delay("*")
                    if crawl_delay and self.config.respect_robots:
                        self._host_delay[p.netloc] = float(crawl_delay)
                        self._emit_log(f"robots.txt Crawl-delay for {p.netloc}: {crawl_delay}s")
            except httpx.HTTPError:
                parser = None
            self._robots[origin] = parser
            return parser

    async def _allowed(self, url: str) -> bool:
        parser = await self._get_robots(url)
        return parser is None or parser.can_fetch(self.config.user_agent, url)

    # ------------------------------------------------------------ images

    async def _download_images(self) -> None:
        img_dir = self.run_dir / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        targets: dict[str, list[dict[str, str]]] = {}
        for page in self.pages:
            for img in page.images:
                targets.setdefault(img["url"], []).append(img)
        if not targets:
            return
        self._emit_log(f"Downloading {len(targets)} images…")
        sem = asyncio.Semaphore(self.config.concurrency * 2)

        async def grab(url: str) -> None:
            async with sem:
                if self._stop:
                    return
                try:
                    resp = await self._client.get(url)
                    ctype = resp.headers.get("content-type", "").split(";")[0].strip()
                    if resp.status_code != 200 or not ctype.startswith("image/") or len(resp.content) > MAX_BODY_BYTES:
                        return
                    ext = Path(urlparse(url).path).suffix.lower()
                    if not ext or len(ext) > 6:
                        ext = mimetypes.guess_extension(ctype) or ".img"
                    path = img_dir / f"{hashlib.md5(url.encode()).hexdigest()}{ext}"
                    path.write_bytes(resp.content)
                    for ref in targets[url]:
                        ref["local_path"] = str(path.relative_to(self.run_dir))
                    self.stats.images_downloaded += 1
                    self._emit_progress()
                except httpx.HTTPError as exc:
                    log.debug("Image failed %s: %s", url, exc)

        await asyncio.gather(*(grab(u) for u in targets))
        self._emit_log(f"Saved {self.stats.images_downloaded} images to {img_dir}")

    # ------------------------------------------------------------ helpers

    def _make_run_dir(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = re.sub(r"[^A-Za-z0-9.-]+", "_", site_key(self.config.url)) or "site"
        return Path(self.config.output_dir) / f"{name}_{stamp}"

    def _attach_file_log(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(self.run_dir / "scrapex.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        self._file_handler = handler

    def _emit_log(self, message: str, level: int = logging.INFO) -> None:
        log.log(level, message)
        self.on_event(CrawlEvent("log", message=message, level=level, stats=self.stats))

    def _emit_progress(self) -> None:
        self.on_event(CrawlEvent("progress", stats=self.stats))

    def _detach_file_log(self) -> None:
        log.removeHandler(self._file_handler)
        self._file_handler.close()


def _match(url: str, pattern: str) -> bool:
    """Glob (``*/blog/*``) or regex (``re:^https://.+/p/\\d+``) pattern match."""
    if pattern.startswith("re:"):
        return re.search(pattern[3:], url) is not None
    return fnmatch.fnmatch(url, pattern) or pattern in url


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return min(float(value), 120.0)
    except ValueError:
        try:
            return max(0.0, min((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds(), 120.0))
        except (TypeError, ValueError):
            return None


def _decode(body: bytes, declared: str | None) -> str:
    m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", body[:4096], re.I)
    for encoding in (declared, m.group(1).decode() if m else None, "utf-8"):
        if encoding:
            try:
                return body.decode(encoding, errors="replace")
            except LookupError:
                continue
    return body.decode("utf-8", errors="replace")


def _has_h2() -> bool:
    try:
        import h2  # noqa: F401
        return True
    except ImportError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
