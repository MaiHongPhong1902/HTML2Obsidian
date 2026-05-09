"""
cleaner.py — Convert raw HTML → clean Markdown, optimised for LLM consumption.

Strategy:
1. Use trafilatura to extract main content (strips nav/ads/footer)
2. Use markitdown (if available) to convert to high-quality Markdown
3. Fallback: BeautifulSoup plain-text extraction
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional


class PageCleaner:
    """Convert HTML → clean Markdown."""

    def __init__(self, prefer_markitdown: bool = True):
        self.prefer_markitdown = prefer_markitdown

    def clean(self, html: str, url: str = "") -> str:
        """
        Return clean Markdown from HTML.
        Tries methods in priority order:
        1. markitdown (high quality)
        2. trafilatura (fast, good noise removal)
        3. BeautifulSoup fallback
        """
        if self.prefer_markitdown:
            result = self._clean_markitdown(html, url)
            if result:
                return self._post_process(result)

        result = self._clean_trafilatura(html, url)
        if result:
            return self._post_process(result)

        return self._post_process(self._clean_beautifulsoup(html))

    # ------------------------------------------------------------------
    # Method 1: markitdown
    # ------------------------------------------------------------------

    def _clean_markitdown(self, html: str, url: str) -> Optional[str]:
        try:
            from markitdown import MarkItDown
            md_converter = MarkItDown()

            # markitdown accepts a file or URL — write HTML to temp file then convert
            with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False
            ) as f:
                f.write(html)
                tmp_path = f.name

            result = md_converter.convert(tmp_path)
            Path(tmp_path).unlink(missing_ok=True)
            return result.text_content if result and result.text_content else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Method 2: trafilatura
    # ------------------------------------------------------------------

    def _clean_trafilatura(self, html: str, url: str) -> Optional[str]:
        try:
            import trafilatura

            text = trafilatura.extract(
                html,
                url=url or None,
                output_format="markdown",
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
            )
            return text or None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Method 3: BeautifulSoup fallback
    # ------------------------------------------------------------------

    def _clean_beautifulsoup(self, html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # Remove unwanted tags
            for tag in soup(["script", "style", "nav", "footer", "header",
                              "aside", "form", "noscript"]):
                tag.decompose()

            # Replace iframe/frame with placeholder text (keep src for later pipeline processing)
            for tag in soup.find_all(["iframe", "frame"]):
                src = tag.get("src", "")
                if src and not src.startswith(("about:", "javascript:", "data:")):
                    placeholder = soup.new_tag("p")
                    placeholder.string = f"[📎 Embedded frame: {src}]"
                    tag.replace_with(placeholder)
                else:
                    tag.decompose()

            # Extract main content area
            main = (
                soup.find("main")
                or soup.find("article")
                or soup.find(id=re.compile(r"content|main|body", re.I))
                or soup.find(class_=re.compile(r"content|main|article|post", re.I))
                or soup.find("body")
            )

            if not main:
                return soup.get_text(separator="\n", strip=True)

            lines = []
            for elem in main.descendants:
                if not hasattr(elem, "name"):
                    continue
                if elem.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    level = int(elem.name[1])
                    lines.append(f"\n{'#' * level} {elem.get_text(strip=True)}\n")
                elif elem.name == "p":
                    text = elem.get_text(strip=True)
                    if text:
                        lines.append(text + "\n")
                elif elem.name == "li":
                    text = elem.get_text(strip=True)
                    if text:
                        lines.append(f"- {text}")
                elif elem.name == "a":
                    href = elem.get("href", "")
                    text = elem.get_text(strip=True)
                    if href and text:
                        lines.append(f"[{text}]({href})")

            return "\n".join(lines)
        except Exception:
            return html[:5000]  # worst-case: return raw HTML truncated

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _post_process(self, text: str) -> str:
        """Strip excess whitespace and normalize."""
        if not text:
            return ""
        # Replace multiple consecutive blank lines with one
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip trailing whitespace from each line
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return text.strip()
