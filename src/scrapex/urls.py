"""URL normalisation and filtering helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|_ga|ref_src)$", re.I)
SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".avif",
    ".pdf", ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".dmg", ".msi", ".apk",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".webm", ".wav", ".ogg", ".flac",
    ".css", ".js", ".json", ".xml", ".rss", ".woff", ".woff2", ".ttf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv",
}


def normalize_url(url: str) -> str | None:
    """Canonical form used for de-duplication: no fragment, no tracking params,
    lower-case host, default ports dropped, sorted query."""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    if p.port and not ((p.scheme == "http" and p.port == 80) or (p.scheme == "https" and p.port == 443)):
        host = f"{host}:{p.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)))
    path = re.sub(r"/{2,}", "/", p.path) or "/"
    return urlunparse((p.scheme, host, path, "", query, ""))


def site_key(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_same_site(url: str, root_url: str) -> bool:
    """True when ``url`` is on the root host or one of its subdomains (www-insensitive)."""
    host, root = site_key(url), site_key(root_url)
    return host == root or host.endswith("." + root)


def looks_like_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    dot = path.rfind(".")
    return dot == -1 or path[dot:] not in SKIP_EXTENSIONS
