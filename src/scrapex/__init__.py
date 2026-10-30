"""ScrapeX - a fast, polite, async website scraper with a terminal UI."""

from scrapex.config import ScrapeConfig
from scrapex.crawler import Crawler, CrawlReport
from scrapex.models import PageResult

__all__ = ["Crawler", "CrawlReport", "PageResult", "ScrapeConfig"]
__version__ = "2.0.0"
