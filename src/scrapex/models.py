"""Result data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PageResult:
    url: str
    depth: int
    status: int | None = None
    final_url: str | None = None
    content_type: str | None = None
    elapsed_ms: int = 0
    fetched_at: str = ""
    error: str | None = None
    duplicate_of: str | None = None

    title: str = ""
    description: str = ""
    canonical: str = ""
    lang: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    opengraph: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    json_ld: list[Any] = field(default_factory=list)
    headings: dict[str, list[str]] = field(default_factory=dict)
    text: str = ""
    word_count: int = 0
    internal_links: list[dict[str, str]] = field(default_factory=list)
    external_links: list[dict[str, str]] = field(default_factory=list)
    images: list[dict[str, str]] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    custom: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 400

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
