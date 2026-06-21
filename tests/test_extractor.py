"""Unit tests for PageExtractor / YouTubeExtractor (no network)."""

from bs4 import BeautifulSoup

from tools.extractor import PageExtractor, YouTubeExtractor


SAMPLE_HTML = """
<html lang="en">
  <head>
    <title>Sample Page</title>
    <meta name="description" content="A sample description">
    <meta name="keywords" content="alpha, beta, gamma">
    <link rel="canonical" href="https://example.com/page">
  </head>
  <body>
    <nav><a href="/about">About</a></nav>
    <main>
      <h1>Main Heading</h1>
      <a href="/internal">Internal Link</a>
      <a href="https://other.com/x">External Link</a>
      <input type="text" name="q" id="search" placeholder="Search">
      <button id="go">Go</button>
    </main>
  </body>
</html>
"""


def test_extract_metadata():
    ex = PageExtractor()
    result = ex.extract(SAMPLE_HTML, base_url="https://example.com/page")
    md = result.metadata
    assert md.title == "Sample Page"
    assert md.description == "A sample description"
    assert md.lang == "en"
    assert md.keywords == ["alpha", "beta", "gamma"]
    assert md.canonical == "https://example.com/page"


def test_extract_links_classified():
    ex = PageExtractor()
    result = ex.extract(SAMPLE_HTML, base_url="https://example.com/page")
    internal_hrefs = {l["href"] for l in result.links.internal}
    external_hrefs = {l["href"] for l in result.links.external}
    assert "https://example.com/internal" in internal_hrefs
    assert "https://example.com/about" in internal_hrefs
    assert "https://other.com/x" in external_hrefs


def test_extract_interactives():
    ex = PageExtractor()
    result = ex.extract(SAMPLE_HTML, base_url="https://example.com/page")
    iv = result.interactives
    assert any(b["id"] == "go" for b in iv.buttons)
    assert any(i["name"] == "q" for i in iv.inputs)


def test_css_selector_prefers_id():
    soup = BeautifulSoup('<input id="email" name="email" type="text">', "lxml")
    el = soup.find("input")
    assert PageExtractor._css_selector(el) == "#email"


def test_css_selector_without_id():
    soup = BeautifulSoup('<input name="email" type="text">', "lxml")
    el = soup.find("input")
    sel = PageExtractor._css_selector(el)
    assert sel == 'input[name="email"][type="text"]'


def test_youtube_video_id():
    assert YouTubeExtractor._extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeExtractor._extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert YouTubeExtractor._extract_video_id("https://example.com") is None
