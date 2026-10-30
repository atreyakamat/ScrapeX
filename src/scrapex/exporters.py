"""Write crawl results to disk in several formats."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from scrapex.crawler import CrawlReport
from scrapex.models import PageResult


def export(report: CrawlReport) -> list[Path]:
    report.run_dir.mkdir(parents=True, exist_ok=True)
    writers = {"json": _json, "jsonl": _jsonl, "csv": _csv, "md": _markdown, "sqlite": _sqlite}
    written: list[Path] = []
    for fmt in report.config.formats:
        written.extend(writers[fmt](report))
    return written


def _summary(report: CrawlReport) -> dict:
    s = report.stats
    return {
        "start_url": report.config.url,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "stopped_early": report.stopped,
        "elapsed_seconds": round(s.elapsed, 2),
        "pages_ok": s.ok,
        "pages_failed": s.failed,
        "pages_skipped": s.skipped,
        "duplicates": s.duplicates,
        "bytes_downloaded": s.bytes,
        "images_downloaded": s.images_downloaded,
        "emails": sorted({e for p in report.pages for e in p.emails}),
        "phones": sorted({t for p in report.pages for t in p.phones}),
        "config": report.config.to_dict(),
    }


def _json(report: CrawlReport) -> list[Path]:
    path = report.run_dir / "results.json"
    payload = {"summary": _summary(report), "pages": [p.to_dict() for p in report.pages]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return [path]


def _jsonl(report: CrawlReport) -> list[Path]:
    path = report.run_dir / "pages.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for page in report.pages:
            f.write(json.dumps(page.to_dict(), ensure_ascii=False, default=str) + "\n")
    return [path]


def _write_csv(path: Path, header: list[str], rows) -> Path:
    # utf-8-sig so Excel opens non-ASCII text correctly
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _csv(report: CrawlReport) -> list[Path]:
    d = report.run_dir
    pages = _write_csv(
        d / "pages.csv",
        ["url", "final_url", "status", "depth", "title", "description", "h1", "word_count",
         "internal_links", "external_links", "images", "emails", "phones", "elapsed_ms", "duplicate_of", "error",
         *(f"custom:{k}" for k in report.config.selectors)],
        (
            [p.url, p.final_url, p.status, p.depth, p.title, p.description, " | ".join(p.headings.get("h1", [])),
             p.word_count, len(p.internal_links), len(p.external_links), len(p.images), "; ".join(p.emails),
             "; ".join(p.phones), p.elapsed_ms, p.duplicate_of or "", p.error or "",
             *(" | ".join(p.custom.get(k, [])) for k in report.config.selectors)]
            for p in report.pages
        ),
    )
    links = _write_csv(
        d / "links.csv",
        ["source_page", "url", "text", "type", "rel"],
        (
            [p.url, link["url"], link["text"], kind, link.get("rel", "")]
            for p in report.pages
            for kind, group in (("internal", p.internal_links), ("external", p.external_links))
            for link in group
        ),
    )
    images = _write_csv(
        d / "images.csv",
        ["source_page", "url", "alt", "title", "kind", "local_path"],
        ([p.url, i["url"], i.get("alt", ""), i.get("title", ""), i.get("kind", "img"), i.get("local_path", "")]
         for p in report.pages for i in p.images),
    )
    return [pages, links, images]


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown(report: CrawlReport) -> list[Path]:
    s = _summary(report)
    ok_pages = [p for p in report.pages if p.ok]
    failed = [p for p in report.pages if not p.ok]
    ext_domains = Counter(
        link["url"].split("/")[2] for p in report.pages for link in p.external_links if link["url"].count("/") >= 2
    )

    lines = [
        f"# ScrapeX report - {report.config.url}",
        "",
        f"*{report.started_at} → {report.finished_at}*" + (" *(stopped early)*" if report.stopped else ""),
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Pages crawled | {s['pages_ok']} |",
        f"| Failed | {s['pages_failed']} |",
        f"| Skipped (robots / non-HTML / off-site) | {s['pages_skipped']} |",
        f"| Duplicate content | {s['duplicates']} |",
        f"| Total words | {sum(p.word_count for p in ok_pages):,} |",
        f"| Unique images | {len({i['url'] for p in report.pages for i in p.images})} |",
        f"| Downloaded | {s['bytes_downloaded'] / 1024 / 1024:.2f} MB in {s['elapsed_seconds']}s |",
        "",
    ]
    if s["emails"] or s["phones"]:
        lines += ["## Contacts found", ""]
        lines += [f"- ✉️ {e}" for e in s["emails"]] + [f"- 📞 {t}" for t in s["phones"]] + [""]

    lines += ["## Pages", "", "| # | Page | Status | Words | Links | Images |", "|---|---|---|---|---|---|"]
    for n, p in enumerate(ok_pages, 1):
        title = _md_escape(p.title or p.url)[:80]
        lines.append(f"| {n} | [{title}]({p.url}) | {p.status} | {p.word_count} | "
                     f"{len(p.internal_links) + len(p.external_links)} | {len(p.images)} |")
    lines.append("")

    issues = _seo_issues(ok_pages)
    if issues:
        lines += ["## SEO checks", ""] + [f"- **{k}**: {len(v)} page(s) - " + ", ".join(v[:5]) + (" …" if len(v) > 5 else "")
                                          for k, v in issues.items()] + [""]
    if failed:
        lines += ["## Errors", ""] + [f"- `{p.url}` - {p.error or p.status}" for p in failed] + [""]
    if ext_domains:
        lines += ["## Top external domains", ""] + [f"- {d} ({c})" for d, c in ext_domains.most_common(15)] + [""]

    lines += ["## Content", ""]
    for p in ok_pages:
        if p.duplicate_of:
            continue
        lines += [f"### {p.title or p.url}", "", f"<{p.url}>", ""]
        if p.description:
            lines += [f"> {p.description}", ""]
        lines += [p.text[:3000] + (" …" if len(p.text) > 3000 else ""), ""]

    path = report.run_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return [path]


def _seo_issues(pages: list[PageResult]) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}

    def flag(name: str, page: PageResult) -> None:
        issues.setdefault(name, []).append(page.url)

    titles = Counter(p.title for p in pages if p.title)
    for p in pages:
        if not p.title:
            flag("Missing <title>", p)
        elif titles[p.title] > 1:
            flag("Duplicate <title>", p)
        if not p.description:
            flag("Missing meta description", p)
        if len(p.headings.get("h1", [])) != 1:
            flag("Not exactly one <h1>", p)
        if any(not i.get("alt") and i.get("kind", "img") == "img" for i in p.images):
            flag("Images without alt text", p)
        if p.word_count < 100:
            flag("Thin content (<100 words)", p)
    return issues


def _sqlite(report: CrawlReport) -> list[Path]:
    path = report.run_dir / "results.sqlite"
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript("""
            CREATE TABLE pages (url TEXT PRIMARY KEY, final_url TEXT, status INTEGER, depth INTEGER, title TEXT,
                description TEXT, lang TEXT, canonical TEXT, word_count INTEGER, text TEXT, elapsed_ms INTEGER,
                error TEXT, duplicate_of TEXT, data JSON);
            CREATE TABLE links (source TEXT, url TEXT, text TEXT, external INTEGER);
            CREATE TABLE images (source TEXT, url TEXT, alt TEXT, local_path TEXT);
            CREATE INDEX links_url ON links(url);
        """)
        for p in report.pages:
            con.execute(
                "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.url, p.final_url, p.status, p.depth, p.title, p.description, p.lang, p.canonical, p.word_count,
                 p.text, p.elapsed_ms, p.error, p.duplicate_of, json.dumps(p.to_dict(), default=str)),
            )
            con.executemany("INSERT INTO links VALUES (?,?,?,?)",
                            [(p.url, lk["url"], lk["text"], 0) for lk in p.internal_links]
                            + [(p.url, lk["url"], lk["text"], 1) for lk in p.external_links])
            con.executemany("INSERT INTO images VALUES (?,?,?,?)",
                            [(p.url, i["url"], i.get("alt", ""), i.get("local_path")) for i in p.images])
        con.commit()
    finally:
        con.close()
    return [path]
