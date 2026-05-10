"""
pipeline.py — Full pipeline: URL → clean Markdown + metadata + links + images + summary.

Main entry point for agent use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .cleaner import PageCleaner
from .extractor import ExtractResult, PageExtractor
from .fetcher import FetchResult, PageFetcher
from .summarizer import PageSummarizer, SummaryResult


@dataclass
class PipelineResult:
    # Input
    url: str

    # Fetch
    status_code: int = 0
    rendered: bool = False
    fetch_error: Optional[str] = None
    _html: str = ""                       # raw HTML (used internally by domain extractors)

    # Content
    clean_markdown: str = ""      # cleaned main content
    metadata_markdown: str = ""   # metadata + links + images as Markdown
    screenshot_b64: Optional[str] = None

    # Extracted raw
    extract: Optional[ExtractResult] = None

    # Summary
    summary: Optional[SummaryResult] = None

    # Browser context (network, metrics, embedded JSON, JSON-LD)
    browser_context: Optional[dict] = None

    # ----------------------------------------------------------------
    # Utility: export as a single complete Markdown for agent
    # ----------------------------------------------------------------

    def to_markdown(
        self,
        include_content: bool = True,
        include_metadata: bool = True,
        include_summary: bool = True,
    ) -> str:
        parts = []

        if include_summary and self.summary and self.summary.summary:
            parts.append("# 📝 Summary\n")
            parts.append(self.summary.summary)
            if self.summary.input_tokens:
                parts.append(
                    f"\n\n> _Tokens: {self.summary.input_tokens} in / "
                    f"{self.summary.output_tokens} out — model: {self.summary.model}_"
                )

        if include_content and self.clean_markdown:
            parts.append("\n\n---\n# 📄 Page Content\n")
            parts.append(self.clean_markdown)

        if include_metadata and self.metadata_markdown:
            parts.append("\n\n---\n")
            parts.append(self.metadata_markdown)

        if self.fetch_error:
            parts.append(f"\n\n> ⚠️ Fetch error: `{self.fetch_error}`")

        return "\n".join(parts).strip()


class BrowserPipeline:
    """
    Full web scraping pipeline for agent use.

    Basic usage:
        pipeline = BrowserPipeline()
        result = pipeline.run("https://example.com")
        print(result.to_markdown())

    Custom:
        pipeline = BrowserPipeline(
            render_js=True,
            screenshot=True,
            summarize=True,
            summarizer_provider="ollama",
            summarizer_model="phi3:mini",
        )
    """

    def __init__(
        self,
        # Fetch options
        render_js: bool = True,
        screenshot: bool = False,
        screenshot_path: Optional[str] = None,
        scroll_to_bottom: bool = False,
        timeout: float = 30.0,
        browser_profile: Optional[str] = None,
        capture_network: bool = False,         # capture XHR/fetch requests for browser_context
        wait_for_selector: Optional[str] = None,   # wait for CSS selector before DOM snapshot
        wait_for_timeout: float = 10.0,            # max seconds to wait for selector
        # Summarize options
        summarize: bool = False,
        summarizer_provider: str = "ollama",
        summarizer_model: str = "llama3.2:3b",
        summarizer_base_url: str = "http://localhost:11434",
        summarizer_api_key: str = "",
        max_summary_words: int = 300,
    ):
        self.render_js = render_js
        self.screenshot = screenshot
        self.screenshot_path = screenshot_path
        self.scroll_to_bottom = scroll_to_bottom
        self.summarize = summarize
        self.wait_for_selector = wait_for_selector
        self.wait_for_timeout = wait_for_timeout

        self._fetcher = PageFetcher(
            timeout=timeout,
            browser_profile=browser_profile,
            capture_network=capture_network,
        )
        self._extractor = PageExtractor()
        self._cleaner = PageCleaner()
        self._summarizer = PageSummarizer(
            provider=summarizer_provider,
            model=summarizer_model,
            base_url=summarizer_base_url,
            api_key=summarizer_api_key,
            max_words=max_summary_words,
        ) if summarize else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, url: str) -> PipelineResult:
        """Run the full pipeline synchronously."""
        result = PipelineResult(url=url)

        # 1. Fetch
        fetch: FetchResult = self._fetcher.fetch(
            url,
            render_js=self.render_js,
            screenshot=self.screenshot,
            screenshot_path=self.screenshot_path,
            scroll_to_bottom=self.scroll_to_bottom,
            wait_for_selector=self.wait_for_selector,
            wait_for_timeout=self.wait_for_timeout,
        )

        result.status_code = fetch.status_code
        result.rendered = fetch.rendered
        result.fetch_error = fetch.error
        result.screenshot_b64 = fetch.screenshot_b64
        result._html = fetch.html or ""   # keep raw HTML for domain extractors

        # Aggregate browser context from fetch result
        ctx: dict = {}
        if fetch.network_requests:
            ctx["network_requests"] = fetch.network_requests
        if fetch.page_metrics:
            ctx["page_metrics"] = fetch.page_metrics
        if fetch.embedded_json:
            ctx["embedded_json"] = fetch.embedded_json
        if fetch.json_ld:
            ctx["json_ld"] = fetch.json_ld
        if fetch.lazy_images_resolved:
            ctx["lazy_images_resolved"] = fetch.lazy_images_resolved
        if fetch.dom_index:
            ctx["dom_index"] = fetch.dom_index
        ctx["spa_framework"] = fetch.spa_framework
        result.browser_context = ctx

        if fetch.error or not fetch.html:
            return result

        # 2. Extract metadata / links / images / layout
        extract = self._extractor.extract(
            fetch.html,
            base_url=fetch.url or url,
            spa_framework=fetch.spa_framework,
            has_shadow_dom=fetch.has_shadow_dom,
        )
        result.extract = extract
        result.metadata_markdown = self._extractor.to_markdown(extract)
        if getattr(extract, "lowcode", None):
            ctx["lowcode"] = {
                "platform": extract.lowcode.platform,
                "indicators": extract.lowcode.indicators,
                "components_count": len(extract.lowcode.components),
                "schema_components_count": len(extract.lowcode.schema_components),
            }
            result.browser_context = ctx

        # 3. Clean HTML → Markdown
        if fetch.is_binary:
            # PDF/DOCX: text already converted by markitdown, extract from <pre> tag in HTML
            import re as _re
            m = _re.search(r"<pre>(.*?)</pre>", fetch.html, _re.DOTALL)
            raw = m.group(1) if m else ""
            # Unescape HTML entities
            raw = raw.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            result.clean_markdown = raw.strip()
        else:
            result.clean_markdown = self._cleaner.clean(fetch.html, url=fetch.url or url)

        # 4. Process iframes
        if result.extract and result.extract.iframes:
            iframe_sections = []

            for iframe in result.extract.iframes:
                itype = iframe.get("type", "")
                src = iframe.get("src", "")

                # --- YouTube embed ---
                if itype == "youtube" and iframe.get("video_id"):
                    try:
                        from .extractor import YouTubeExtractor
                        yt_url = f"https://www.youtube.com/watch?v={iframe['video_id']}"
                        yt_info = YouTubeExtractor().extract(yt_url)
                        if yt_info:
                            iframe_sections.append(
                                f"\n---\n## 🎬 Embedded video: {yt_info.title}\n{yt_info.to_markdown()}"
                            )
                    except Exception:
                        iframe_sections.append(f"\n---\n## 🎬 Embedded video\n[YouTube]({src})")

                # --- Same-origin frame (fetched by Playwright) ---
                elif itype == "same_origin":
                    # Look up frame by URL in fetch.frames
                    frame_html = next(
                        (f["html"] for f in fetch.frames if f["url"] == src and f["html"]),
                        ""
                    )
                    if frame_html:
                        frame_md = self._cleaner.clean(frame_html, url=src)
                        if frame_md:
                            iframe_sections.append(
                                f"\n---\n## 🗂️ Embedded frame ({src})\n{frame_md[:3000]}"
                            )
                    else:
                        iframe_sections.append(f"\n---\n## 🗂️ Embedded frame\n[{src}]({src})")

                # --- Spotify embed ---
                elif itype == "spotify":
                    iframe_sections.append(f"\n---\n## 🎵 Spotify embed\n[Open Spotify]({src})")

                # --- Google Maps embed ---
                elif itype == "maps":
                    iframe_sections.append(f"\n---\n## 🗺️ Map embed\n[View map]({src})")

                # --- Other cross-origin ---
                elif itype == "cross_origin" and src:
                    iframe_sections.append(f"\n---\n## 🔗 Embedded content\n[{src}]({src})")

            if iframe_sections:
                result.clean_markdown += "\n".join(iframe_sections)

        # 5. Summarize (optional)
        if self._summarizer and result.clean_markdown:
            result.summary = self._summarizer.summarize(result.clean_markdown)

        return result

    def quick(self, url: str) -> str:
        """
        Shortcut: run pipeline without JS rendering or summarization.
        Returns clean Markdown immediately (fastest path).
        """
        fetch = self._fetcher.fetch(url, render_js=False)
        if fetch.error or not fetch.html:
            return f"> ⚠️ Error: {fetch.error or 'No content retrieved'}"
        return self._cleaner.clean(fetch.html, url=fetch.url or url)
