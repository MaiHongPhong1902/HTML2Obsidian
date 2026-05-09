"""
fetcher.py — Fetch web page content via Playwright (supports SPA/JS).
Also supports fast fallback via httpx when JS rendering is not needed.

Browser profile support
-----------------------
Pass `browser_profile` to reuse an existing browser profile (cookies, login
sessions, extensions).  Accepts either:
  - A predefined shortcut string: "chrome", "chrome-dev", "edge", "firefox"
  - An absolute path to a user-data directory (any Chromium-based browser)

On Windows the shortcuts resolve to the default profile directories:
  chrome      → %LOCALAPPDATA%/Google/Chrome/User Data
  chrome-dev  → %LOCALAPPDATA%/Google/Chrome Dev/User Data
  edge        → %LOCALAPPDATA%/Microsoft/Edge/User Data
  firefox     → %APPDATA%/Mozilla/Firefox/Profiles  (uses first profile)

Example:
    fetcher = PageFetcher(browser_profile="chrome")
    result  = fetcher.fetch("https://mail.google.com")
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

# Predefined profile shortcuts (Windows paths)
_PROFILE_SHORTCUTS: dict[str, str] = {
    "chrome":      str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"),
    "chrome-dev":  str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome Dev" / "User Data"),
    "edge":        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"),
    "firefox":     str(Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"),
}

# Binary/document file extensions — do not use Playwright for these
_BINARY_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".epub", ".zip", ".rar", ".7z",
    ".gz", ".tar", ".mp3", ".mp4", ".avi", ".mkv",
}


@dataclass
class FetchResult:
    url: str
    html: str
    status_code: int
    screenshot_b64: Optional[str] = None   # base64 PNG, None if not captured
    rendered: bool = False                 # True if JS was rendered via Playwright
    error: Optional[str] = None
    is_binary: bool = False                # True if file is PDF/DOCX/..., text already cleaned
    frames: list[dict] = None              # Same-origin frames: [{"url", "html"}]
    spa_framework: str = "static"          # static | react | vue | angular | next.js | nuxt
    has_shadow_dom: bool = False           # True if shadow DOM detected

    def __post_init__(self):
        if self.frames is None:
            self.frames = []


class PageFetcher:
    """
    Fetch web page content.

    - render_js=False  → use httpx (fast, low resource)
    - render_js=True   → use Playwright (supports SPA, lazy-load, etc.)
    """

    def __init__(
        self,
        timeout: float = 30.0,
        wait_until: str = "domcontentloaded",  # 'load' | 'networkidle' | 'domcontentloaded'
        viewport: dict = None,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        browser_profile: Optional[str] = None,
    ):
        self.timeout = timeout
        self.wait_until = wait_until
        self.viewport = viewport or {"width": 1280, "height": 800}
        self.user_agent = user_agent
        self.browser_profile = self._resolve_profile(browser_profile)

    @staticmethod
    def _resolve_profile(profile: Optional[str]) -> Optional[str]:
        """Resolve shortcut name or path → absolute user-data dir, or None."""
        if not profile:
            return None
        resolved = _PROFILE_SHORTCUTS.get(profile.lower(), profile)
        p = Path(resolved)
        if not p.exists():
            raise FileNotFoundError(
                f"Browser profile directory not found: {resolved}\n"
                f"Available shortcuts: {list(_PROFILE_SHORTCUTS)}"
            )
        # Firefox stores profiles in sub-dirs; pick the first *.default* one
        if "Firefox" in resolved and p.is_dir():
            candidates = sorted(p.glob("*.default*"))
            if candidates:
                return str(candidates[0])
        return resolved

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        url: str,
        render_js: bool = True,
        screenshot: bool = False,
        screenshot_path: Optional[str] = None,
        scroll_to_bottom: bool = False,
    ) -> FetchResult:
        """Synchronous wrapper — calls asyncio.run() internally."""
        return asyncio.run(
            self.afetch(url, render_js, screenshot, screenshot_path, scroll_to_bottom)
        )

    async def afetch(
        self,
        url: str,
        render_js: bool = True,
        screenshot: bool = False,
        screenshot_path: Optional[str] = None,
        scroll_to_bottom: bool = False,
    ) -> FetchResult:
        """Async: choose between httpx and Playwright."""
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in _BINARY_EXTENSIONS:
            return await self._fetch_binary(url)
        if render_js:
            return await self._fetch_playwright(
                url, screenshot, screenshot_path, scroll_to_bottom
            )
        return await self._fetch_httpx(url)

    # ------------------------------------------------------------------
    # Playwright fetch
    # ------------------------------------------------------------------

    async def _fetch_playwright(
        self,
        url: str,
        screenshot: bool,
        screenshot_path: Optional[str],
        scroll_to_bottom: bool,
    ) -> FetchResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return FetchResult(
                url=url,
                html="",
                status_code=0,
                error="playwright not installed. Run: pip install playwright && playwright install chromium",
            )

        try:
            async with async_playwright() as p:
                if self.browser_profile:
                    # Use persistent context so cookies/sessions are loaded from the profile.
                    # Chrome must be closed before Playwright opens the same profile.
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=self.browser_profile,
                        headless=True,
                        viewport=self.viewport,
                        user_agent=self.user_agent,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    browser = None  # persistent context owns everything
                else:
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        viewport=self.viewport,
                        user_agent=self.user_agent,
                    )
                page = await context.new_page()

                response = await page.goto(
                    url,
                    timeout=self.timeout * 1000,
                    wait_until=self.wait_until,
                )
                status_code = response.status if response else 0

                if scroll_to_bottom:
                    await self._scroll_to_bottom(page)

                html = await page.content()

                # SPA: wait for networkidle so JS finishes rendering (max 5s)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                    html = await page.content()  # re-fetch after SPA render
                except Exception:
                    pass  # timeout OK — use current html

                # SPA framework detection + shadow DOM
                spa_info = await page.evaluate("""
                () => {
                    const srcs = Array.from(document.querySelectorAll('script[src]'))
                        .map(s => s.src.toLowerCase()).join(' ');
                    const inline = Array.from(document.querySelectorAll('script:not([src])'))
                        .map(s => (s.textContent||'').slice(0,3000)).join(' ').toLowerCase();
                    const body = document.body ? document.body.innerHTML.slice(0,3000).toLowerCase() : '';

                    let framework = 'static';
                    if (document.getElementById('__next') || body.includes('__next_data__'))
                        framework = 'next.js';
                    else if (document.getElementById('__nuxt') || body.includes('__nuxt__'))
                        framework = 'nuxt';
                    else if (document.querySelector('[ng-version]') || srcs.includes('angular'))
                        framework = 'angular';
                    else if (document.querySelector('[data-v-app]') || srcs.includes('vue'))
                        framework = 'vue';
                    else if ((document.getElementById('root')||document.getElementById('app'))
                             && (srcs.includes('react') || inline.includes('react')))
                        framework = 'react';
                    else if (srcs.includes('react') || inline.includes('reactdom'))
                        framework = 'react';

                    // Shadow DOM detection
                    let hasShadow = false;
                    try {
                        const walker = document.createTreeWalker(
                            document.body, 0x1, null);
                        let n = walker.currentNode;
                        while (n && !hasShadow) {
                            if (n.shadowRoot) hasShadow = true;
                            n = walker.nextNode();
                        }
                    } catch(e) {}

                    return {framework, hasShadow};
                }
                """)

                spa_framework = spa_info.get("framework", "static") if spa_info else "static"
                has_shadow_dom = bool(spa_info.get("hasShadow", False)) if spa_info else False

                # If shadow DOM detected: inject shadow content so the parser can see it
                if has_shadow_dom:
                    shadow_html = await page.evaluate("""
                    () => {
                        function extractShadowHtml(root) {
                            let out = '';
                            const walker = document.createTreeWalker(root, 0x1, null);
                            let node = walker.currentNode;
                            while (node) {
                                if (node.shadowRoot) {
                                    out += '<!-- shadow:' + (node.tagName||'').toLowerCase() + ' -->';
                                    out += node.shadowRoot.innerHTML;
                                }
                                node = walker.nextNode();
                            }
                            return out;
                        }
                        return extractShadowHtml(document.body);
                    }
                    """)
                    if shadow_html:
                        # Append shadow content to body before </body>
                        html = html.replace(
                            "</body>",
                            f'<div id="__shadow_content__">{shadow_html}</div></body>'
                        )
                frames_data = []
                main_frame = page.main_frame
                for frame in page.frames:
                    if frame == main_frame:
                        continue
                    frame_url = frame.url
                    if not frame_url or frame_url.startswith(("about:", "javascript:", "data:")):
                        continue
                    try:
                        frame_html = await frame.content()
                        frames_data.append({"url": frame_url, "html": frame_html})
                    except Exception:
                        # Cross-origin frame → cannot read, skip
                        frames_data.append({"url": frame_url, "html": ""})

                screenshot_b64: Optional[str] = None
                if screenshot:
                    png_bytes = await page.screenshot(full_page=True)
                    screenshot_b64 = base64.b64encode(png_bytes).decode()
                    if screenshot_path:
                        Path(screenshot_path).write_bytes(png_bytes)

                await context.close()
                if browser:
                    await browser.close()

                return FetchResult(
                    url=url,
                    html=html,
                    status_code=status_code,
                    screenshot_b64=screenshot_b64,
                    rendered=True,
                    frames=frames_data,
                    spa_framework=spa_framework,
                    has_shadow_dom=has_shadow_dom,
                )
        except Exception as exc:
            return FetchResult(url=url, html="", status_code=0, error=str(exc))

    # ------------------------------------------------------------------
    # Binary/document fetch (PDF, DOCX, ...)
    # ------------------------------------------------------------------

    async def _fetch_binary(self, url: str) -> FetchResult:
        """Download binary file and convert to text using markitdown."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            ) as client:
                resp = await client.get(url)
                status_code = resp.status_code
                if status_code != 200:
                    return FetchResult(
                        url=url, html="", status_code=status_code,
                        error=f"HTTP {status_code}"
                    )
                content_bytes = resp.content

            # Write to temp file then convert with markitdown
            ext = Path(urlparse(url).path).suffix.lower() or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(content_bytes)
                tmp_path = tmp.name

            text = ""
            try:
                from markitdown import MarkItDown
                md = MarkItDown()
                result = md.convert(tmp_path)
                text = result.text_content if result and result.text_content else ""
            except Exception:
                pass
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            if not text:
                return FetchResult(
                    url=url, html="", status_code=status_code,
                    error="Could not convert file content"
                )

            # Extract title from first non-empty line
            doc_title = ""
            for line in text.splitlines():
                line = line.strip()
                if line and len(line) > 3:
                    doc_title = line[:120]
                    break

            # Wrap in HTML with <title> so extractor can pick it up
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html = (
                f"<html><head><title>{doc_title}</title></head>"
                f"<body><article><pre>{escaped}</pre></article></body></html>"
            )
            return FetchResult(
                url=url,
                html=html,
                status_code=status_code,
                rendered=False,
                is_binary=True,
            )
        except Exception as exc:
            return FetchResult(url=url, html="", status_code=0, error=str(exc))

    # ------------------------------------------------------------------
    # httpx fetch (fast fallback)
    # ------------------------------------------------------------------

    async def _fetch_httpx(self, url: str) -> FetchResult:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent},
            ) as client:
                resp = await client.get(url)
                return FetchResult(
                    url=str(resp.url),
                    html=resp.text,
                    status_code=resp.status_code,
                    rendered=False,
                )
        except Exception as exc:
            return FetchResult(url=url, html="", status_code=0, error=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _scroll_to_bottom(page) -> None:
        """Scroll to bottom to trigger lazy-load."""
        prev_height = 0
        for _ in range(10):
            height = await page.evaluate("document.body.scrollHeight")
            if height == prev_height:
                break
            prev_height = height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.8)
