"""Command-line entry point.

    scrapex                      -> interactive terminal UI
    scrapex crawl <url> [opts]   -> headless crawl with a live progress bar
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from scrapex import __version__, history
from scrapex.config import EXPORT_FORMATS, ScrapeConfig
from scrapex.crawler import Crawler, CrawlEvent
from scrapex.exporters import export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrapex", description="Fast, polite website scraper with a terminal UI.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", help="Open the interactive terminal UI (default)")

    c = sub.add_parser("crawl", help="Crawl a site without the UI")
    c.add_argument("url")
    c.add_argument("-n", "--max-pages", type=int, default=50)
    c.add_argument("-d", "--max-depth", type=int, default=3)
    c.add_argument("-c", "--concurrency", type=int, default=5)
    c.add_argument("--delay", type=float, default=0.5, help="Seconds between requests to the same host")
    c.add_argument("--timeout", type=float, default=20.0)
    c.add_argument("--retries", type=int, default=2)
    c.add_argument("-f", "--format", dest="formats", action="append", choices=EXPORT_FORMATS,
                   help="Output format (repeatable). Default: json, csv, md")
    c.add_argument("-o", "--output", dest="output_dir", help="Output directory (default: ./output or $SCRAPEX_OUTPUT)")
    c.add_argument("--include", action="append", default=[], help="Only crawl URLs matching glob or re:<regex>")
    c.add_argument("--exclude", action="append", default=[], help="Skip URLs matching glob or re:<regex>")
    c.add_argument("-s", "--selector", action="append", default=[], metavar="NAME=CSS",
                   help="Extract a custom field, e.g. -s price=.product .price")
    c.add_argument("--js", dest="render_js", action="store_true", help="Render pages with headless Chromium")
    c.add_argument("--images", dest="download_images", action="store_true", help="Download images")
    c.add_argument("--all-domains", dest="same_domain", action="store_false", help="Follow external links too")
    c.add_argument("--ignore-robots", dest="respect_robots", action="store_false")
    c.add_argument("--no-sitemap", dest="use_sitemap", action="store_false")
    c.add_argument("--user-agent")
    c.add_argument("--proxy", help="e.g. http://user:pass@host:8080 or socks5://host:1080")
    c.add_argument("-q", "--quiet", action="store_true", help="Only print the final summary")
    return parser


def config_from_args(args: argparse.Namespace) -> ScrapeConfig:
    selectors = {}
    for item in args.selector:
        name, sep, css = item.partition("=")
        if not sep or not name.strip() or not css.strip():
            raise ValueError(f"--selector must look like NAME=CSS, got {item!r}")
        selectors[name.strip()] = css.strip()
    kwargs = dict(
        url=args.url, max_pages=args.max_pages, max_depth=args.max_depth, concurrency=args.concurrency,
        delay=args.delay, timeout=args.timeout, retries=args.retries, same_domain=args.same_domain,
        respect_robots=args.respect_robots, use_sitemap=args.use_sitemap, render_js=args.render_js,
        download_images=args.download_images, include_patterns=args.include, exclude_patterns=args.exclude,
        selectors=selectors, formats=args.formats or ["json", "csv", "md"], proxy=args.proxy,
    )
    if args.output_dir:
        kwargs["output_dir"] = args.output_dir
    if args.user_agent:
        kwargs["user_agent"] = args.user_agent
    return ScrapeConfig(**kwargs)


def run_headless(config: ScrapeConfig, quiet: bool = False) -> int:
    console = Console()
    progress = Progress(
        SpinnerColumn(), TextColumn("[bold cyan]{task.description}"), BarColumn(), MofNCompleteColumn(),
        TextColumn("[green]{task.fields[ok]} ok [red]{task.fields[failed]} err"), TimeElapsedColumn(),
        console=console, disable=quiet,
    )
    task = progress.add_task("Crawling", total=config.max_pages, ok=0, failed=0)

    def on_event(event: CrawlEvent) -> None:
        s = event.stats
        if s:
            progress.update(task, completed=min(s.fetched, config.max_pages), ok=s.ok, failed=s.failed)
        if event.kind == "log" and not quiet and event.level >= logging.INFO:
            style = "red" if event.level >= logging.WARNING else "dim"
            progress.console.print(f"[{style}]{event.message}[/]", highlight=False)

    crawler = Crawler(config, on_event)
    with progress:
        try:
            report = asyncio.run(crawler.run())
        except KeyboardInterrupt:
            console.print("[yellow]Interrupted.[/]")
            return 130
    files = export(report)
    history.record(config.output_dir, config.url, report.stats.ok, str(report.run_dir))

    table = Table(title=f"ScrapeX - {config.url}", show_header=False, title_style="bold")
    s = report.stats
    table.add_row("Pages OK", f"[green]{s.ok}")
    table.add_row("Failed", f"[red]{s.failed}")
    table.add_row("Skipped", str(s.skipped))
    table.add_row("Duplicates", str(s.duplicates))
    table.add_row("Images saved", str(s.images_downloaded))
    table.add_row("Time", f"{s.elapsed:.1f}s ({s.pages_per_sec:.2f} pages/s)")
    table.add_row("Output", "\n".join(str(f) for f in files))
    console.print(table)
    return 0 if s.ok else 1


def main(argv: list[str] | None = None) -> int:
    # Legacy Windows consoles default to cp1252 and choke on ✓ / → in log lines.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.command == "crawl":
        try:
            config = config_from_args(args)
        except ValueError as exc:
            Console(stderr=True).print(f"[red]error:[/] {exc}")
            return 2
        return run_headless(config, args.quiet)

    from scrapex.tui import ScrapeXApp
    ScrapeXApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
