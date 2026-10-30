"""HTML -> structured data extraction."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from scrapex.models import PageResult
from scrapex.urls import is_same_site, normalize_url

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "form", "nav", "footer", "header", "aside")
MAX_TABLES = 20
MAX_TEXT_CHARS = 200_000


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for item in items:
        seen.setdefault(item[key], item)
    return list(seen.values())


def extract(html: str, page: PageResult, root_url: str, selectors: dict[str, str] | None = None) -> PageResult:
    """Populate ``page`` with everything we can learn from ``html``."""
    base = page.final_url or page.url
    soup = BeautifulSoup(html, "lxml")

    base_tag = soup.find("base", href=True)
    if isinstance(base_tag, Tag):
        base = urljoin(base, str(base_tag["href"]))

    html_tag = soup.find("html")
    if isinstance(html_tag, Tag):
        page.lang = str(html_tag.get("lang", "") or "")
    if soup.title:
        page.title = _clean(soup.title.get_text())

    _extract_meta(soup, page, base)
    _extract_json_ld(soup, page)
    _extract_links(soup, page, base, root_url)
    _extract_images(soup, page, base)
    _extract_tables(soup, page)

    if selectors:
        for name, css in selectors.items():
            try:
                page.custom[name] = [_clean(el.get_text(" ")) for el in soup.select(css)]
            except Exception as exc:  # invalid selector
                page.custom[name] = [f"<selector error: {exc}>"]

    # Text extraction is destructive, so it runs last.
    _extract_headings(soup, page)
    _extract_text(soup, page)
    return page


def _extract_meta(soup: BeautifulSoup, page: PageResult, base: str) -> None:
    for meta in soup.find_all("meta"):
        key = meta.get("property") or meta.get("name") or meta.get("itemprop")
        content = meta.get("content")
        if not key or content is None:
            continue
        key, content = str(key).strip(), _clean(str(content))
        if key.startswith("og:"):
            page.opengraph[key[3:]] = content
        elif key.startswith("twitter:"):
            page.twitter[key[8:]] = content
        else:
            page.meta[key] = content

    page.description = page.meta.get("description") or page.opengraph.get("description", "")
    if not page.title:
        page.title = page.opengraph.get("title", "")
    canonical = soup.find("link", rel="canonical", href=True)
    if isinstance(canonical, Tag):
        page.canonical = urljoin(base, str(canonical["href"]))


def _extract_json_ld(soup: BeautifulSoup, page: PageResult) -> None:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, list):
            page.json_ld.extend(data)
        else:
            page.json_ld.append(data)


def _extract_links(soup: BeautifulSoup, page: PageResult, base: str, root_url: str) -> None:
    internal, external, emails, phones = [], [], set(), set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        lower = href.lower()
        if lower.startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr:
                emails.add(addr)
            continue
        if lower.startswith("tel:"):
            phones.add(href[4:].strip())
            continue
        if lower.startswith(("javascript:", "data:", "#")) or not href:
            continue
        absolute = normalize_url(urljoin(base, href))
        if absolute is None:
            continue
        link = {"url": absolute, "text": _clean(a.get_text(" "))[:200]}
        if a.get("rel"):
            link["rel"] = " ".join(a["rel"]) if isinstance(a["rel"], list) else str(a["rel"])
        (internal if is_same_site(absolute, root_url) else external).append(link)

    page.internal_links = _dedupe(internal, "url")
    page.external_links = _dedupe(external, "url")
    page.emails = sorted(emails)
    page.phones = sorted(phones)


def _extract_images(soup: BeautifulSoup, page: PageResult, base: str) -> None:
    images: list[dict[str, str]] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src and img.get("srcset"):
            src = str(img["srcset"]).split(",")[0].split()[0]
        if not src or str(src).startswith("data:"):
            continue
        images.append({
            "url": urljoin(base, str(src).strip()),
            "alt": _clean(str(img.get("alt", ""))),
            "title": _clean(str(img.get("title", ""))),
        })
    for el in soup.find_all(style=True):
        for match in CSS_URL_RE.findall(str(el["style"])):
            if not match.startswith("data:"):
                images.append({"url": urljoin(base, match.strip()), "alt": "", "title": "", "kind": "background"})
    if page.opengraph.get("image"):
        images.append({"url": urljoin(base, page.opengraph["image"]), "alt": "", "title": "", "kind": "og:image"})
    page.images = [i for i in _dedupe(images, "url") if urlparse(i["url"]).scheme in ("http", "https")]


def _extract_tables(soup: BeautifulSoup, page: PageResult) -> None:
    for table in soup.find_all("table")[:MAX_TABLES]:
        rows = []
        for tr in table.find_all("tr"):
            cells = [_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if rows:
            page.tables.append(rows)


def _extract_headings(soup: BeautifulSoup, page: PageResult) -> None:
    for level in ("h1", "h2", "h3"):
        found = [t for t in (_clean(h.get_text(" ")) for h in soup.find_all(level)) if t]
        if found:
            page.headings[level] = found


def _extract_text(soup: BeautifulSoup, page: PageResult) -> None:
    # Listing pages often have many <article> cards; only treat <article> as the main content when it's unique.
    articles = soup.find_all("article", limit=2)
    root = (soup.find("main") or soup.find(attrs={"role": "main"}) or (articles[0] if len(articles) == 1 else None)
            or soup.body or soup)
    for tag in root.find_all(NOISE_TAGS):
        tag.decompose()

    blocks: list[str] = []
    for el in root.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "td", "dd", "dt"]):
        if el.find(["p", "li", "blockquote", "pre"]):  # avoid double-counting nested blocks
            continue
        text = _clean(el.get_text(" "))
        if text:
            blocks.append(text)
    if not blocks:  # sites built from bare divs
        blocks = [line for line in (_clean(s) for s in root.get_text("\n").split("\n")) if line]

    seen: set[str] = set()
    unique = [b for b in blocks if not (b in seen or seen.add(b))]
    page.text = "\n\n".join(unique)[:MAX_TEXT_CHARS]
    page.word_count = len(page.text.split())

    page.emails = sorted(set(page.emails) | set(EMAIL_RE.findall(page.text)))
