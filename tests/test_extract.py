import pytest

from scrapex.config import ScrapeConfig
from scrapex.extract import extract
from scrapex.models import PageResult
from scrapex.urls import is_same_site, looks_like_page, normalize_url

HTML = """<html lang="de"><head><title> Shop </title>
<meta name="description" content="Best   shop"><meta property="og:title" content="OG Shop">
<meta name="twitter:card" content="summary"><link rel="canonical" href="/home">
<script type="application/ld+json">[{"@type": "Product"}, {"@type": "Offer"}]</script>
<script type="application/ld+json">not json</script></head>
<body><header>Header junk</header><nav><a href="/nav">Nav</a></nav>
<article><h1>Title</h1><h2>Sub</h2><p>First paragraph.</p><ul><li>Item <b>one</b></li></ul><p>First paragraph.</p>
<a href="mailto:hi@x.test?subject=Hi">mail</a><a href="tel:+1 555">call</a><a href="javascript:void(0)">js</a>
<a href="other#frag">Other</a><a href="https://sub.example.com/x">Sub</a><a href="https://elsewhere.org">Ext</a>
<img data-src="/lazy.jpg" alt="Lazy"><img src="data:image/png;base64,AAA"><div style="background-image:url('/bg.png')"></div>
</article><footer>Footer junk</footer></body></html>"""


def test_extract_everything():
    page = extract(HTML, PageResult(url="https://example.com/shop/", depth=0), "https://example.com/")
    assert page.title == "Shop" and page.lang == "de"
    assert page.description == "Best shop"
    assert page.opengraph == {"title": "OG Shop"} and page.twitter == {"card": "summary"}
    assert page.canonical == "https://example.com/home"
    assert [d["@type"] for d in page.json_ld] == ["Product", "Offer"]
    assert page.headings == {"h1": ["Title"], "h2": ["Sub"]}
    assert page.text.split("\n\n") == ["Title", "Sub", "First paragraph.", "Item one"]
    assert "junk" not in page.text
    assert page.emails == ["hi@x.test"] and page.phones == ["+1 555"]
    assert {lk["url"] for lk in page.internal_links} == {
        "https://example.com/nav", "https://example.com/shop/other", "https://sub.example.com/x"}
    assert [lk["url"] for lk in page.external_links] == ["https://elsewhere.org/"]
    assert {i["url"] for i in page.images} == {"https://example.com/lazy.jpg", "https://example.com/bg.png"}


@pytest.mark.parametrize("raw, expected", [
    ("https://Example.com:443/a//b?b=2&a=1&utm_source=x#top", "https://example.com/a/b?a=1&b=2"),
    ("http://example.com", "http://example.com/"),
    ("ftp://example.com/file", None),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_url_helpers():
    assert is_same_site("https://www.example.com/x", "https://example.com/")
    assert not is_same_site("https://notexample.com/", "https://example.com/")
    assert not looks_like_page("https://example.com/a.PDF")
    assert looks_like_page("https://example.com/a.html")


def test_config_validation():
    assert ScrapeConfig(url="example.com").url == "https://example.com"
    with pytest.raises(ValueError):
        ScrapeConfig(url="")
    with pytest.raises(ValueError):
        ScrapeConfig(url="https://x.com", formats=["xml"])
