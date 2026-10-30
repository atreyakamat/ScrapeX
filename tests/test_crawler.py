import json

from scrapex import Crawler, ScrapeConfig
from scrapex.cli import main
from scrapex.exporters import export


def make_config(url, tmp_path, **kw):
    return ScrapeConfig(url=url, output_dir=str(tmp_path), delay=0, concurrency=3, **kw)


async def test_full_crawl_respects_robots_and_finds_sitemap(site_url, tmp_path):
    report = await Crawler(make_config(site_url, tmp_path, formats=["json", "csv", "md", "jsonl", "sqlite"])).run()
    urls = {p.url.removeprefix(site_url.rstrip("/")) for p in report.pages}

    assert {"/", "/about", "/blog/one", "/blog/two", "/blog/three", "/sitemap-only", "/missing"} <= urls
    assert "/private/secret" not in urls  # robots.txt
    assert not any(u.endswith(".pdf") for u in urls)
    assert report.stats.failed == 1  # /missing -> 404

    files = {f.name for f in export(report)}
    assert {"results.json", "pages.csv", "links.csv", "images.csv", "report.md", "pages.jsonl", "results.sqlite"} <= files
    data = json.loads((report.run_dir / "results.json").read_text(encoding="utf-8"))
    assert "sales@acme.test" in data["summary"]["emails"]


async def test_limits_depth_and_pages(site_url, tmp_path):
    report = await Crawler(make_config(site_url, tmp_path, max_depth=1, use_sitemap=False)).run()
    assert max(p.depth for p in report.pages) == 1
    assert not any("/blog/two" in p.url for p in report.pages)

    report = await Crawler(make_config(site_url, tmp_path, max_pages=2)).run()
    assert len(report.pages) == 2


async def test_include_exclude_and_selectors(site_url, tmp_path):
    cfg = make_config(site_url, tmp_path, exclude_patterns=["*/blog/*"], selectors={"price": ".price"},
                      respect_robots=False, use_sitemap=False)
    report = await Crawler(cfg).run()
    urls = [p.url for p in report.pages]
    assert not any("/blog/" in u for u in urls)
    assert any("/private/secret" in u for u in urls)  # robots ignored
    assert report.pages[0].custom["price"] == ["$9.99"]


async def test_image_download(site_url, tmp_path):
    report = await Crawler(make_config(site_url, tmp_path, max_pages=1, download_images=True)).run()
    assert report.stats.images_downloaded >= 1
    assert any(i.get("local_path") for i in report.pages[0].images)


def test_cli_headless(site_url, tmp_path):
    code = main(["crawl", site_url, "-n", "3", "-o", str(tmp_path), "--delay", "0", "-q", "-f", "json"])
    assert code == 0
    assert list(tmp_path.glob("*/results.json"))
