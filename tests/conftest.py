import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PAGE = """<!doctype html><html lang="en"><head><title>{title}</title>
<meta name="description" content="About {title}"><meta property="og:image" content="/og.png">
<script type="application/ld+json">{{"@type": "Organization", "name": "Acme"}}</script></head>
<body><nav><a href="/">Home</a></nav><main><h1>{title}</h1><p>Welcome to {title}. Contact sales@acme.test.</p>
{links}<img src="/img/{slug}.png" alt="pic"><span class="price">$9.99</span>
<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></main>
<footer>footer text</footer></body></html>"""

SITE = {
    "/": ("Home", ["/about", "/blog/one?utm_source=x", "/private/secret", "/file.pdf", "https://external.test/"]),
    "/about": ("About", ["/", "/blog/one", "/missing"]),
    "/blog/one": ("Post One", ["/blog/two"]),
    "/blog/two": ("Post Two", ["/blog/three"]),
    "/blog/three": ("Post Three", []),
    "/private/secret": ("Secret", []),
    "/sitemap-only": ("From sitemap", []),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        host = f"http://{self.headers['Host']}"
        if path == "/robots.txt":
            return self._send(200, f"User-agent: *\nDisallow: /private/\nSitemap: {host}/sitemap.xml\n".encode(), "text/plain")
        if path == "/sitemap.xml":
            return self._send(200, f"<urlset><url><loc>{host}/sitemap-only</loc></url></urlset>".encode(), "application/xml")
        if path.endswith(".png"):
            return self._send(200, b"\x89PNG\r\n\x1a\nfake", "image/png")
        if path not in SITE:
            return self._send(404, b"<html><title>Not found</title></html>")
        title, links = SITE[path]
        html = PAGE.format(title=title, slug=title.lower().replace(" ", "-"),
                           links="".join(f'<a href="{href}">{href}</a>' for href in links))
        self._send(200, html.encode())


@pytest.fixture(scope="session")
def site_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
