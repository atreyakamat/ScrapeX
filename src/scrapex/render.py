"""Optional headless-browser rendering for JavaScript-heavy sites (Playwright)."""

from __future__ import annotations

import asyncio

from scrapex.config import ScrapeConfig

BLOCKED_RESOURCES = {"image", "media", "font"}


class Renderer:
    def __init__(self, config: ScrapeConfig) -> None:
        self.config = config
        self._sem = asyncio.Semaphore(config.concurrency)
        self._pw = self._browser = self._context = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "JavaScript rendering needs Playwright: pip install 'scrapex[js]' && playwright install chromium"
            ) from exc
        self._pw = await async_playwright().start()
        launch = {"headless": True}
        if self.config.proxy:
            launch["proxy"] = {"server": self.config.proxy}
        self._browser = await self._pw.chromium.launch(**launch)
        self._context = await self._browser.new_context(user_agent=self.config.user_agent)

        async def block_heavy(route):
            if route.request.resource_type in BLOCKED_RESOURCES:
                await route.abort()
            else:
                await route.continue_()

        await self._context.route("**/*", block_heavy)

    async def fetch(self, url: str) -> tuple[int, str, str, str | None]:
        async with self._sem:
            page = await self._context.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout * 1000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass  # long-polling sites never go idle; DOM is good enough
                status = resp.status if resp else 200
                ctype = (resp.headers.get("content-type", "text/html") if resp else "text/html").split(";")[0]
                if "html" not in ctype:
                    return status, page.url, ctype, None
                return status, page.url, ctype, await page.content()
            finally:
                await page.close()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
