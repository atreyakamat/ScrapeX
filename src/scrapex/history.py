"""Remembers recently scraped sites so the TUI can offer them for re-selection."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MAX_ENTRIES = 25


def _path(output_dir: str) -> Path:
    return Path(output_dir) / ".history.json"


def load(output_dir: str) -> list[dict]:
    try:
        return json.loads(_path(output_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def record(output_dir: str, url: str, pages: int, run_dir: str) -> None:
    entries = [e for e in load(output_dir) if e.get("url") != url]
    entries.insert(0, {"url": url, "pages": pages, "run_dir": run_dir,
                       "when": datetime.now().strftime("%Y-%m-%d %H:%M")})
    try:
        _path(output_dir).parent.mkdir(parents=True, exist_ok=True)
        _path(output_dir).write_text(json.dumps(entries[:MAX_ENTRIES], indent=2), encoding="utf-8")
    except OSError:
        pass
