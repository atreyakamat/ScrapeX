"""Interactive terminal UI built with Textual."""

from __future__ import annotations

import json
import logging

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    OptionList,
    ProgressBar,
    RichLog,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from scrapex import __version__, history
from scrapex.config import ScrapeConfig, default_output_dir
from scrapex.crawler import Crawler, CrawlEvent, CrawlStats
from scrapex.exporters import export
from scrapex.models import PageResult

PRESETS = {
    "quick": dict(max_pages=10, max_depth=1, concurrency=4, delay=0.2),
    "standard": dict(max_pages=50, max_depth=3, concurrency=5, delay=0.5),
    "deep": dict(max_pages=500, max_depth=8, concurrency=8, delay=0.5),
}


class StatCard(Static):
    def __init__(self, label: str, id: str) -> None:
        super().__init__(id=id, classes="stat")
        self.border_title = label
        self.update("-")


class ScrapeXApp(App):
    TITLE = "ScrapeX"
    SUB_TITLE = f"v{__version__} · polite async web scraper"
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #sidebar { width: 46; padding: 0 1; border-right: tall $primary-background; }
    #sidebar Label.section { margin-top: 1; color: $accent; text-style: bold; }
    #sidebar Input { margin-bottom: 0; }
    .row { height: auto; }
    .row > Vertical { width: 1fr; height: auto; }
    .hint { color: $text-muted; }
    #recent { height: 7; }
    #formats { height: auto; max-height: 7; }
    #buttons { height: auto; margin-top: 1; }
    #buttons Button { width: 1fr; }
    #presets Button { width: 1fr; min-width: 6; }
    #main { padding: 0 1; }
    #stats { height: 5; }
    .stat { width: 1fr; height: 5; border: round $primary; content-align: center middle; text-style: bold; }
    #progress { margin: 0 0 1 0; }
    #progress Bar { width: 1fr; }
    #log, #pages { height: 1fr; }
    #inspect, #files { padding: 0 1; }
    """
    BINDINGS = [
        Binding("ctrl+r", "start", "Start crawl", priority=True),
        Binding("ctrl+x", "stop", "Stop", priority=True),
        Binding("ctrl+l", "focus_url", "Edit URL"),
        Binding("ctrl+e", "export_selected", "Show page JSON"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.crawler: Crawler | None = None
        self.pages: dict[str, PageResult] = {}
        self.output_dir = default_output_dir()

    # ----------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with VerticalScroll(id="sidebar"):
                yield Label("Target site", classes="section")
                yield Input(placeholder="https://example.com", id="url")
                yield Label("Recent sites  (Enter to select)", classes="section")
                yield OptionList(id="recent")
                yield Label("Preset", classes="section")
                with Horizontal(id="presets", classes="row"):
                    yield Button("Quick", id="preset-quick", compact=True)
                    yield Button("Standard", id="preset-standard", compact=True)
                    yield Button("Deep", id="preset-deep", compact=True)
                yield Label("Limits", classes="section")
                with Horizontal(classes="row"):
                    with Vertical():
                        yield Label("Max pages", classes="hint")
                        yield Input("50", id="max_pages", type="integer")
                    with Vertical():
                        yield Label("Max depth", classes="hint")
                        yield Input("3", id="max_depth", type="integer")
                with Horizontal(classes="row"):
                    with Vertical():
                        yield Label("Concurrency", classes="hint")
                        yield Input("5", id="concurrency", type="integer")
                    with Vertical():
                        yield Label("Delay (s/host)", classes="hint")
                        yield Input("0.5", id="delay", type="number")
                yield Label("Filters", classes="section")
                yield Input(placeholder="Include: */blog/*, re:\\d{4}", id="include")
                yield Input(placeholder="Exclude: */tag/*, *?page=*", id="exclude")
                yield Input(placeholder="Custom fields: price=.price; sku=[itemprop=sku]", id="selectors")
                yield Label("Options", classes="section")
                yield Checkbox("Stay on this domain", True, id="same_domain")
                yield Checkbox("Respect robots.txt", True, id="respect_robots")
                yield Checkbox("Seed from sitemap.xml", True, id="use_sitemap")
                yield Checkbox("Render JavaScript (Playwright)", False, id="render_js")
                yield Checkbox("Download images", False, id="download_images")
                yield Label("Export formats", classes="section")
                yield SelectionList[str](
                    ("JSON (full)", "json", True), ("CSV (pages/links/images)", "csv", True),
                    ("Markdown report", "md", True), ("JSON Lines", "jsonl", False), ("SQLite", "sqlite", False),
                    id="formats",
                )
                with Horizontal(id="buttons"):
                    yield Button("▶ Start", id="start", variant="success")
                    yield Button("■ Stop", id="stop", variant="error", disabled=True)
            with Vertical(id="main"):
                with Horizontal(id="stats"):
                    yield StatCard("Crawled", "s-fetched")
                    yield StatCard("OK", "s-ok")
                    yield StatCard("Errors", "s-failed")
                    yield StatCard("Queued", "s-queued")
                    yield StatCard("Speed", "s-speed")
                yield ProgressBar(id="progress", show_eta=False)
                with TabbedContent(id="tabs"):
                    with TabPane("Activity", id="tab-log"):
                        yield RichLog(id="log", markup=True, wrap=True, highlight=False)
                    with TabPane("Pages", id="tab-pages"):
                        yield DataTable(id="pages", cursor_type="row", zebra_stripes=True)
                    with TabPane("Inspect", id="tab-inspect"):
                        with VerticalScroll():
                            yield Markdown("Select a row in **Pages** to inspect it.", id="inspect")
                    with TabPane("Files", id="tab-files"):
                        with VerticalScroll():
                            yield Markdown("Results will appear here when the crawl finishes.", id="files")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#pages", DataTable)
        table.add_column("St", key="status", width=4)
        table.add_column("D", key="depth", width=2)
        table.add_column("Title", key="title", width=36)
        table.add_column("URL", key="url")
        table.add_column("Words", key="words", width=7)
        table.add_column("Links", key="links", width=6)
        table.add_column("Imgs", key="imgs", width=5)
        table.add_column("ms", key="ms", width=6)
        self._load_history()
        self.query_one("#url", Input).focus()
        self._log("[b]Welcome to ScrapeX.[/b] Enter a URL (or pick a recent site) and press "
                  "[b]Ctrl+R[/b] or [b]Start[/b].")

    def _load_history(self) -> None:
        recent = self.query_one("#recent", OptionList)
        recent.clear_options()
        entries = history.load(self.output_dir)
        if not entries:
            recent.add_option(Option("[dim]No sites scraped yet[/dim]", disabled=True))
        for e in entries:
            recent.add_option(Option(f"{e['url']}  [dim]{e['pages']}p · {e['when']}[/dim]", id=e["url"]))

    # ---------------------------------------------------------------- actions

    def action_focus_url(self) -> None:
        self.query_one("#url", Input).focus()

    @on(OptionList.OptionSelected, "#recent")
    def pick_recent(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.query_one("#url", Input).value = event.option.id
            self.notify(f"Selected {event.option.id}")

    @on(Button.Pressed, "#presets Button")
    def apply_preset(self, event: Button.Pressed) -> None:
        name = event.button.id.removeprefix("preset-")
        for key, value in PRESETS[name].items():
            self.query_one(f"#{key}", Input).value = str(value)
        self.notify(f"Preset: {name}")

    @on(Input.Submitted, "#url")
    @on(Button.Pressed, "#start")
    def action_start(self) -> None:
        if self.crawler is not None:
            self.notify("A crawl is already running", severity="warning")
            return
        try:
            config = self._read_config()
        except ValueError as exc:
            self.notify(str(exc), title="Invalid settings", severity="error")
            return
        self._reset_views(config)
        self.crawl(config)

    @on(Button.Pressed, "#stop")
    def action_stop(self) -> None:
        if self.crawler:
            self.crawler.stop()

    def action_export_selected(self) -> None:
        table = self.query_one("#pages", DataTable)
        if table.row_count == 0:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        page = self.pages.get(str(row_key.value))
        if page:
            body = json.dumps(page.to_dict(), indent=2, ensure_ascii=False, default=str)
            self.query_one("#inspect", Markdown).update(f"```json\n{body[:60_000]}\n```")
            self.query_one(TabbedContent).active = "tab-inspect"

    @on(DataTable.RowSelected, "#pages")
    def inspect_page(self, event: DataTable.RowSelected) -> None:
        page = self.pages.get(str(event.row_key.value))
        if page:
            self.query_one("#inspect", Markdown).update(_page_markdown(page))
            self.query_one(TabbedContent).active = "tab-inspect"

    # ------------------------------------------------------------------ crawl

    def _read_config(self) -> ScrapeConfig:
        def val(id_: str) -> str:
            return self.query_one(f"#{id_}", Input).value.strip()

        def num(id_: str, cast):
            try:
                return cast(val(id_))
            except ValueError:
                raise ValueError(f"{id_.replace('_', ' ').title()} must be a number") from None

        def split(id_: str) -> list[str]:
            return [p.strip() for p in val(id_).replace(";", ",").split(",") if p.strip()]

        selectors = {}
        for item in val("selectors").split(";"):
            name, sep, css = item.partition("=")
            if sep and name.strip() and css.strip():
                selectors[name.strip()] = css.strip()

        formats = list(self.query_one("#formats", SelectionList).selected)
        if not formats:
            raise ValueError("Pick at least one export format")
        return ScrapeConfig(
            url=val("url"),
            max_pages=num("max_pages", int), max_depth=num("max_depth", int),
            concurrency=num("concurrency", int), delay=num("delay", float),
            include_patterns=split("include"), exclude_patterns=split("exclude"), selectors=selectors,
            formats=formats, output_dir=self.output_dir,
            **{k: self.query_one(f"#{k}", Checkbox).value
               for k in ("same_domain", "respect_robots", "use_sitemap", "render_js", "download_images")},
        )

    def _reset_views(self, config: ScrapeConfig) -> None:
        self.pages.clear()
        self.query_one("#pages", DataTable).clear()
        self.query_one("#log", RichLog).clear()
        self.query_one("#progress", ProgressBar).update(total=config.max_pages, progress=0)
        self.query_one("#start", Button).disabled = True
        self.query_one("#stop", Button).disabled = False
        self.query_one(TabbedContent).active = "tab-log"
        self.sub_title = f"crawling {config.url}"

    @work(exclusive=True, group="crawl")
    async def crawl(self, config: ScrapeConfig) -> None:
        self.crawler = Crawler(config, self._on_event)
        try:
            report = await self.crawler.run()
            files = export(report)
            history.record(config.output_dir, config.url, report.stats.ok, str(report.run_dir))
            self._show_files(report.run_dir, files)
            self.notify(f"Crawled {report.stats.ok} pages → {report.run_dir}", title="Done", timeout=8)
            self._load_history()
        except Exception as exc:
            self._log(f"[red bold]Crawl failed:[/] {exc}")
            self.notify(str(exc), title="Crawl failed", severity="error", timeout=10)
        finally:
            self.crawler = None
            self.query_one("#start", Button).disabled = False
            self.query_one("#stop", Button).disabled = True
            self.sub_title = f"v{__version__} · polite async web scraper"

    def _on_event(self, event: CrawlEvent) -> None:
        if event.stats:
            self._update_stats(event.stats)
        if event.kind == "log" and event.level >= logging.INFO:
            color = {logging.WARNING: "yellow", logging.ERROR: "red"}.get(event.level, "white")
            self._log(f"[{color}]{event.message}[/]")
        elif event.kind == "page" and event.page:
            self._add_page(event.page)

    def _update_stats(self, s: CrawlStats) -> None:
        self.query_one("#s-fetched", Static).update(str(s.fetched))
        self.query_one("#s-ok", Static).update(f"[green]{s.ok}[/]")
        self.query_one("#s-failed", Static).update(f"[red]{s.failed}[/]" if s.failed else "0")
        self.query_one("#s-queued", Static).update(str(max(s.queued - s.fetched - s.skipped, 0)))
        self.query_one("#s-speed", Static).update(f"{s.pages_per_sec:.1f}/s")
        self.query_one("#progress", ProgressBar).update(progress=s.fetched)

    def _add_page(self, p: PageResult) -> None:
        self.pages[p.url] = p
        status = f"[green]{p.status}[/]" if p.ok else f"[red]{p.status or 'ERR'}[/]"
        title = p.title or p.error or ""
        if p.duplicate_of:
            title = f"[dim](dup) {title}[/]"
        self.query_one("#pages", DataTable).add_row(
            status, str(p.depth), title[:60], p.url, str(p.word_count),
            str(len(p.internal_links) + len(p.external_links)), str(len(p.images)), str(p.elapsed_ms), key=p.url,
        )

    def _show_files(self, run_dir, files) -> None:
        lines = [f"## Results saved to\n\n`{run_dir.resolve()}`\n"]
        lines += [f"- `{f.name}` - {f.stat().st_size / 1024:.1f} KB" for f in files]
        images = run_dir / "images"
        if images.exists():
            lines.append(f"- `images/` - {sum(1 for _ in images.iterdir())} files")
        self.query_one("#files", Markdown).update("\n".join(lines))

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)


def _page_markdown(p: PageResult) -> str:
    def esc(text: str) -> str:
        return text.replace("|", "\\|").replace("\n", " ")

    out = [f"# {p.title or p.url}", "", f"<{p.url}>", ""]
    rows = [("Status", p.status), ("Depth", p.depth), ("Language", p.lang or "-"), ("Words", p.word_count),
            ("Load time", f"{p.elapsed_ms} ms"), ("Canonical", p.canonical or "-")]
    if p.final_url and p.final_url != p.url:
        rows.append(("Redirected to", p.final_url))
    if p.duplicate_of:
        rows.append(("Duplicate of", p.duplicate_of))
    if p.error:
        rows.append(("Error", p.error))
    out += ["| | |", "|---|---|"] + [f"| **{k}** | {esc(str(v))} |" for k, v in rows] + [""]
    if p.description:
        out += [f"> {p.description}", ""]
    if p.custom:
        out += ["## Custom fields", ""] + [f"- **{k}**: {esc(' | '.join(v)) or '*(no match)*'}" for k, v in p.custom.items()] + [""]
    for level, items in p.headings.items():
        out += [f"**{level.upper()}**: " + " · ".join(items[:10]), ""]
    if p.emails or p.phones:
        out += ["## Contacts", ""] + [f"- {x}" for x in p.emails + p.phones] + [""]
    if p.opengraph:
        out += ["## OpenGraph", ""] + [f"- **{k}**: {esc(v)}" for k, v in p.opengraph.items()] + [""]
    if p.json_ld:
        types = [str(d.get("@type", "?")) for d in p.json_ld if isinstance(d, dict)]
        out += [f"**Structured data (JSON-LD)**: {', '.join(types) or len(p.json_ld)}", ""]
    if p.tables:
        out += [f"**Tables**: {len(p.tables)}", ""]
    out += [f"## Links ({len(p.internal_links)} internal, {len(p.external_links)} external)", ""]
    out += [f"- [{esc(lk['text']) or lk['url']}]({lk['url']})" for lk in (p.internal_links + p.external_links)[:40]]
    out += ["", f"## Images ({len(p.images)})", ""] + [f"- {i['url']}" + (f" - *{esc(i['alt'])}*" if i.get("alt") else "")
                                                       for i in p.images[:30]]
    out += ["", "## Text", "", p.text[:8000] or "*(no text extracted)*"]
    return "\n".join(out)
