<div align="center">

# 🕷️ ScrapeX

**A fast, polite, async website scraper with an interactive terminal UI.**

Point it at a site, watch it crawl live, and get clean JSON, CSV, Markdown, and SQLite output, plus an SEO report.

[![CI](https://github.com/atreyakamat/ScrapeX/actions/workflows/ci.yml/badge.svg)](https://github.com/atreyakamat/ScrapeX/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## ✨ Features

| | |
|---|---|
| ⚡ **Async & concurrent** | `httpx` + HTTP/2 with configurable workers, connection pooling, and streaming downloads |
| 🖥️ **Terminal UI** | Enter or pick a recent site, choose presets, watch live stats, browse and inspect every page |
| 🤝 **Polite by default** | Honours `robots.txt` and `Crawl-delay`, applies per-host rate limiting, and backs off adaptively on `429`/`5xx` using `Retry-After` |
| 🗺️ **Smart discovery** | Seeds from `sitemap.xml` and sitemap indexes, normalises URLs (strips tracking params, sorts queries), skips binary files, and detects duplicate content |
| 🧠 **Rich extraction** | Title, meta, OpenGraph, Twitter cards, JSON-LD, canonical, language, headings, main-content text, links, images (including lazy and background images), tables, emails, phones |
| 🎯 **Custom fields** | Add your own CSS selectors, e.g. `price=.price` |
| 🔎 **Filters** | Include or exclude URLs with globs (`*/blog/*`) or regexes (`re:/p/\d+`) |
| 🌐 **JavaScript sites** | Optional headless Chromium rendering via Playwright (`--js`) |
| 📦 **Many outputs** | `results.json`, `pages.jsonl`, `pages.csv` / `links.csv` / `images.csv`, `report.md`, `results.sqlite` |
| 📈 **SEO audit** | Flags missing or duplicate titles, missing descriptions, H1 problems, images without alt text, and thin content |
| 🐳 **Dockerised** | One command to run the TUI or headless crawls in a container |

## 🚀 Quick start

### Docker (recommended)

```bash
docker build -t scrapex .

# Interactive terminal UI
docker run -it --rm -v "$PWD/output:/data" scrapex

# Headless crawl
docker run --rm -v "$PWD/output:/data" scrapex crawl https://books.toscrape.com -n 100
```

Or with Compose:

```bash
docker compose run --rm scrapex                                  # TUI
docker compose run --rm scrapex crawl https://example.com -f md  # headless
```

> Need JavaScript rendering? Build with `--build-arg WITH_JS=true` (adds Chromium, about 400 MB).

### Local install

```bash
git clone https://github.com/atreyakamat/ScrapeX.git
cd ScrapeX
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                 # add ".[js]" for Playwright, ".[dev]" for tests
scrapex                          # opens the TUI
```

## 🖥️ Terminal UI

```bash
scrapex
```

```
┌ Target site ───────────────┐ ╭ Crawled ╮╭ OK ╮╭ Errors ╮╭ Queued ╮╭ Speed ╮
│ https://example.com        │ │   42    ││ 41 ││   1    ││   17   ││ 3.2/s │
│ Recent sites               │ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 84%
│  books.toscrape.com  15p   │  Activity │ Pages │ Inspect │ Files
│ Preset [Quick][Std][Deep]  │  ✓ [200] https://example.com/about (512 words)
│ Max pages 50  Depth 3      │  ✓ [200] https://example.com/blog (1204 words)
│ Include / Exclude / Fields │  ✗ https://example.com/old - HTTP 404
│ ☑ robots.txt ☑ sitemap     │
│ [▶ Start]  [■ Stop]        │
└────────────────────────────┘
```

| Key | Action |
|---|---|
| `Ctrl+R` / `Enter` in the URL box | Start crawl |
| `Ctrl+X` | Stop gracefully; results gathered so far are still exported |
| `Ctrl+L` | Jump to the URL box |
| `Enter` on a row in **Pages** | Inspect the page: metadata, headings, links, images, text |
| `Ctrl+E` | Show the selected page as raw JSON |
| `Ctrl+P` | Command palette (themes and more) |
| `Ctrl+Q` | Quit |

## ⌨️ Command line

```bash
scrapex crawl https://example.com \
  -n 200 -d 4 -c 8 --delay 0.3 \
  --include "*/blog/*" --exclude "*/tag/*" \
  -s "author=.byline" -s "date=time[datetime]" \
  -f json -f csv -f md -f sqlite \
  --images
```

| Flag | Default | Description |
|---|---|---|
| `-n, --max-pages` | 50 | Maximum pages to fetch |
| `-d, --max-depth` | 3 | Maximum link depth from the start URL |
| `-c, --concurrency` | 5 | Parallel workers |
| `--delay` | 0.5 | Minimum seconds between requests to the same host |
| `-f, --format` | json, csv, md | `json`, `jsonl`, `csv`, `md`, `sqlite` (repeatable) |
| `-o, --output` | `./output` | Output directory (or set `$SCRAPEX_OUTPUT`) |
| `--include / --exclude` | | Glob or `re:<regex>` URL filters (repeatable) |
| `-s, --selector` | | `NAME=CSS` custom field (repeatable) |
| `--js` | off | Render with headless Chromium |
| `--images` | off | Download images to `images/` |
| `--all-domains` | off | Follow external links too |
| `--ignore-robots` | off | Don't read `robots.txt` |
| `--no-sitemap` | off | Don't seed from `sitemap.xml` |
| `--proxy` | | `http://…` or `socks5://…` |
| `--user-agent` | ScrapeX UA | Custom User-Agent |
| `-q, --quiet` | | Only print the final summary |

## 📂 Output

Each run gets its own folder, `output/<domain>_<timestamp>/`:

```
results.json     summary + every page with all extracted fields
pages.jsonl      one page per line (streaming / big-data friendly)
pages.csv        one row per page (opens cleanly in Excel)
links.csv        every link: source → target, internal/external
images.csv       every image with alt text and local path
report.md        human-readable report: summary, contacts, SEO checks, errors, content
results.sqlite   tables: pages, links, images (query with any SQLite tool)
images/          downloaded images (with --images)
scrapex.log      full debug log
```

## 🐍 Use as a library

```python
import asyncio
from scrapex import Crawler, ScrapeConfig
from scrapex.exporters import export

config = ScrapeConfig(url="https://example.com", max_pages=20, selectors={"price": ".price"})
report = asyncio.run(Crawler(config).run())
for page in report.pages:
    print(page.status, page.title, page.custom.get("price"))
export(report)
```

## 🧪 Development

```bash
pip install -e ".[dev]"
ruff check src/scrapex tests
pytest
```

The test suite starts a local HTTP server with a fake site (robots.txt, sitemap, 404s, images) and drives the crawler, CLI, and TUI end to end, so it needs no internet.

## ⚖️ Scrape responsibly

ScrapeX respects `robots.txt` and rate limits by default. Check a site's terms of service before scraping it, don't overload servers, and handle any personal data you collect (emails, phone numbers) according to applicable law.

## 🤝 Contributing

Issues and PRs are welcome. Please run `ruff` and `pytest` before you open a PR.

## 📄 License

[MIT](LICENSE) © Atreya Kamat
