"""Crawl configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ScrapeX/2.0; +https://github.com/atreyakamat/ScrapeX)"
)
EXPORT_FORMATS = ("json", "jsonl", "csv", "md", "sqlite")


@dataclass
class ScrapeConfig:
    url: str
    max_pages: int = 50
    max_depth: int = 3
    concurrency: int = 5
    delay: float = 0.5
    """Minimum seconds between two requests to the same host."""
    timeout: float = 20.0
    retries: int = 2
    same_domain: bool = True
    respect_robots: bool = True
    use_sitemap: bool = True
    render_js: bool = False
    download_images: bool = False
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    selectors: dict[str, str] = field(default_factory=dict)
    """Custom extraction: field name -> CSS selector."""
    formats: list[str] = field(default_factory=lambda: ["json", "csv", "md"])
    output_dir: str = field(default_factory=lambda: default_output_dir())
    user_agent: str = DEFAULT_USER_AGENT
    proxy: str | None = None

    def __post_init__(self) -> None:
        self.url = normalize_start_url(self.url)
        bad = [f for f in self.formats if f not in EXPORT_FORMATS]
        if bad:
            raise ValueError(f"Unknown export format(s): {', '.join(bad)}")
        if self.max_pages < 1 or self.concurrency < 1 or self.max_depth < 0:
            raise ValueError("max_pages and concurrency must be >= 1, max_depth >= 0")

    def to_dict(self) -> dict:
        return asdict(self)


def default_output_dir() -> str:
    return os.environ.get("SCRAPEX_OUTPUT", "output")


def normalize_start_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise ValueError("URL is required")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Not a valid http(s) URL: {url}")
    return url
