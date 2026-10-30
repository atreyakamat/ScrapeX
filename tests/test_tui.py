from textual.widgets import DataTable, Input

from scrapex.tui import ScrapeXApp


async def test_tui_runs_a_crawl(site_url, tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPEX_OUTPUT", str(tmp_path))
    app = ScrapeXApp()
    async with app.run_test(size=(160, 50)) as pilot:
        app.query_one("#url", Input).value = site_url
        app.query_one("#max_pages", Input).value = "4"
        app.query_one("#delay", Input).value = "0"
        await pilot.press("ctrl+r")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.query_one("#pages", DataTable).row_count == 4
        assert list(tmp_path.glob("*/report.md"))
        assert (tmp_path / ".history.json").exists()


async def test_tui_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRAPEX_OUTPUT", str(tmp_path))
    app = ScrapeXApp()
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.press("ctrl+r")  # empty URL
        await pilot.pause()
        assert app.crawler is None
        assert not list(tmp_path.iterdir())
