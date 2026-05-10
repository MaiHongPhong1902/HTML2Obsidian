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
    network_requests: list = field(default_factory=list)   # [{url, method, status, content_type}] — XHR/fetch
    page_metrics: dict = field(default_factory=dict)       # {load_time_ms, dom_nodes, images, scripts, links}
    embedded_json: dict = field(default_factory=dict)      # window globals (__NEXT_DATA__, __NUXT__, etc.)
    json_ld: list = field(default_factory=list)            # JSON-LD from <script type="application/ld+json">
    lazy_images_resolved: int = 0                          # count of lazy images resolved
    dom_index: dict = field(default_factory=dict)          # semantic DOM index for LLM element queries

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
        capture_network: bool = False,        # capture XHR/fetch requests during page load
    ):
        self.timeout = timeout
        self.wait_until = wait_until
        self.viewport = viewport or {"width": 1280, "height": 800}
        self.user_agent = user_agent
        self.browser_profile = self._resolve_profile(browser_profile)
        self.capture_network = capture_network

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
        wait_for_selector: Optional[str] = None,   # CSS selector to wait for before snapshot
        wait_for_timeout: float = 10.0,             # max seconds to wait for the selector
    ) -> FetchResult:
        """Synchronous wrapper — calls asyncio.run() internally."""
        return asyncio.run(
            self.afetch(
                url, render_js, screenshot, screenshot_path,
                scroll_to_bottom, wait_for_selector, wait_for_timeout,
            )
        )

    async def afetch(
        self,
        url: str,
        render_js: bool = True,
        screenshot: bool = False,
        screenshot_path: Optional[str] = None,
        scroll_to_bottom: bool = False,
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: float = 10.0,
    ) -> FetchResult:
        """Async: choose between httpx and Playwright."""
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in _BINARY_EXTENSIONS:
            return await self._fetch_binary(url)
        if render_js:
            return await self._fetch_playwright(
                url, screenshot, screenshot_path, scroll_to_bottom,
                wait_for_selector, wait_for_timeout,
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
        wait_for_selector: Optional[str] = None,
        wait_for_timeout: float = 10.0,
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

                # --- Network request capture ---
                network_reqs: list[dict] = []
                if self.capture_network:
                    def _on_response(response) -> None:
                        try:
                            if response.request.resource_type in ("xhr", "fetch"):
                                network_reqs.append({
                                    "url": response.url,
                                    "method": response.request.method,
                                    "status": response.status,
                                    "content_type": response.headers.get("content-type", ""),
                                })
                        except Exception:
                            pass
                    page.on("response", _on_response)

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

                # Low-code/no-code renderers often attach controls after the main
                # SPA idle event. Give detected runtimes a short extra settle time.
                try:
                    lowcode_seen = await page.evaluate("""
                    () => Boolean(
                        document.querySelector('.formio, .formio-component, [data-block], [data-widget], [data-container], .osui, [class*="osui-"]')
                        || Array.from(document.scripts).some(s => /formio|outsystems/i.test(s.src || s.textContent || ''))
                    )
                    """)
                    if lowcode_seen:
                        await page.wait_for_timeout(800)
                        html = await page.content()
                except Exception:
                    pass

                # Wait for a specific selector to appear (caller-defined element readiness)
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(
                            wait_for_selector,
                            timeout=wait_for_timeout * 1000,
                            state="visible",
                        )
                        html = await page.content()  # re-snapshot after element appears
                    except Exception:
                        pass  # selector never appeared — continue with current html

                # --- Browser context extraction ---

                # 1. Resolve lazy images (data-src → src) before snapshotting HTML
                lazy_resolved: int = 0
                try:
                    lazy_resolved = await page.evaluate("""
                    () => {
                        let count = 0;
                        const lazyAttrs = [
                            'data-src','data-lazy-src','data-original',
                            'data-lazy','data-srcset','data-bg'
                        ];
                        document.querySelectorAll('img, [data-bg]').forEach(el => {
                            for (const attr of lazyAttrs) {
                                const val = el.getAttribute(attr);
                                if (val && (val.startsWith('http') || val.startsWith('/'))
                                        && el.tagName === 'IMG' && !el.src.startsWith('http')) {
                                    el.src = val;
                                    count++;
                                    break;
                                }
                            }
                        });
                        // Also resolve background-image lazy patterns
                        document.querySelectorAll('[data-bg]').forEach(el => {
                            const val = el.getAttribute('data-bg');
                            if (val) {
                                el.style.backgroundImage = `url('${val}')`;
                                count++;
                            }
                        });
                        return count;
                    }
                    """) or 0
                    if lazy_resolved:
                        html = await page.content()
                except Exception:
                    pass

                # 2. Page performance metrics
                page_metrics: dict = {}
                try:
                    page_metrics = await page.evaluate("""
                    () => {
                        try {
                            const nav = (performance.getEntriesByType('navigation') || [])[0] || {};
                            return {
                                load_time_ms: Math.round(nav.loadEventEnd || 0),
                                dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
                                dom_nodes: document.querySelectorAll('*').length,
                                images: document.images.length,
                                scripts: document.scripts.length,
                                links: document.links.length,
                            };
                        } catch(e) { return {}; }
                    }
                    """) or {}
                except Exception:
                    pass

                # 3. Embedded JSON globals (SSR data: __NEXT_DATA__, __NUXT__, etc.)
                embedded_json: dict = {}
                try:
                    embedded_json = await page.evaluate("""
                    () => {
                        const keys = [
                            '__NEXT_DATA__','__NUXT__','__INITIAL_STATE__',
                            '__APP_STATE__','__PRELOADED_STATE__','__REDUX_STATE__',
                            'initialData','__data__','__STORE__','__APOLLO_STATE__'
                        ];
                        const result = {};
                        for (const k of keys) {
                            try {
                                if (window[k] !== undefined)
                                    result[k] = JSON.parse(JSON.stringify(window[k]));
                            } catch(e) {}
                        }
                        return result;
                    }
                    """) or {}
                except Exception:
                    pass

                # 4. JSON-LD structured data
                json_ld: list = []
                try:
                    json_ld = await page.evaluate("""
                    () => Array.from(
                        document.querySelectorAll('script[type="application/ld+json"]')
                    ).map(s => {
                        try { return JSON.parse(s.textContent); }
                        catch(e) { return null; }
                    }).filter(Boolean)
                    """) or []
                except Exception:
                    pass

                # 5. Semantic DOM index for LLM element queries
                dom_index: dict = {}
                try:
                    dom_index = await page.evaluate("""
                    () => {
                        const T = (el, limit=300) => (el.innerText||el.textContent||'').trim().slice(0,limit);
                        const A = (el, attr) => el.getAttribute(attr)||'';
                        const labelFor = (el) => {
                            const id = A(el, 'id');
                            if (id) {
                                const escaped = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/"/g, '\\"');
                                const direct = document.querySelector(`label[for="${escaped}"]`);
                                if (direct) return T(direct, 120);
                            }
                            const labelledBy = A(el, 'aria-labelledby');
                            if (labelledBy) {
                                const labels = labelledBy.split(/\\s+/).map(x => document.getElementById(x)).filter(Boolean).map(x => T(x, 80));
                                if (labels.length) return labels.join(' ').slice(0, 120);
                            }
                            const closest = el.closest('label,.formio-component,.form-group,[data-block],[data-widget]');
                            if (closest) {
                                const label = closest.querySelector('label,.control-label,.formio-label');
                                if (label) return T(label, 120);
                            }
                            return A(el, 'aria-label') || A(el, 'placeholder') || '';
                        };
                        const componentKey = (el) => {
                            let node = el;
                            for (let i = 0; node && i < 5; i++, node = node.parentElement) {
                                for (const attr of ['data-key','data-name','data-field','data-input','name','id']) {
                                    const raw = A(node, attr);
                                    if (!raw) continue;
                                    const m = raw.match(/^data\\[([^\\]]+)\\]/);
                                    return (m ? m[1] : raw).slice(0, 120);
                                }
                            }
                            return '';
                        };

                        // Headings
                        const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
                            .map((el,i) => ({
                                i, level: parseInt(el.tagName[1]), text: T(el,200),
                                id: A(el,'id'), href: A(el,'id') ? '#'+A(el,'id') : ''
                            })).slice(0,80);

                        // Tables
                        const tables = Array.from(document.querySelectorAll('table')).map((t,i) => {
                            const ths = Array.from(t.querySelectorAll('th')).map(th => T(th,100));
                            const rows = Array.from(t.querySelectorAll('tr')).slice(0,10).map(tr =>
                                Array.from(tr.querySelectorAll('td')).map(td => T(td,100))
                            ).filter(r => r.length);
                            return {i, headers: ths, rows};
                        }).slice(0,20);

                        // Code blocks
                        const code = Array.from(document.querySelectorAll('pre code, pre'))
                            .map((el,i) => {
                                const lang = (A(el,'class').match(/language-([\\w-]+)/)||[])[1] || '';
                                return {i, lang, text: T(el,800)};
                            }).filter(c => c.text.length > 10).slice(0,30);

                        // Lists
                        const lists = Array.from(document.querySelectorAll('ul,ol')).map((el,i) => ({
                            i, ordered: el.tagName==='OL',
                            items: Array.from(el.querySelectorAll(':scope > li')).map(li => T(li,150)).slice(0,20)
                        })).filter(l => l.items.length).slice(0,25);

                        // Images
                        const images = Array.from(document.querySelectorAll('img')).map((el,i) => ({
                            i, src: A(el,'src')||A(el,'data-src'), alt: A(el,'alt'), width: el.naturalWidth||0
                        })).filter(im => im.src).slice(0,40);

                        // Key-value pairs from <dl> definition lists
                        const key_values = Array.from(document.querySelectorAll('dl')).flatMap(dl => {
                            const pairs = [];
                            let key = '';
                            dl.querySelectorAll('dt,dd').forEach(el => {
                                if (el.tagName==='DT') key = T(el,100);
                                else if (key) { pairs.push({key, value: T(el,200)}); key=''; }
                            });
                            return pairs;
                        }).slice(0,40);

                        // Named sections: heading + first 200 chars of following text
                        const sections = [];
                        document.querySelectorAll('h1,h2,h3').forEach(h => {
                            let text = '';
                            let n = h.nextElementSibling;
                            while (n && !['H1','H2','H3'].includes(n.tagName) && text.length < 200) {
                                text += ' ' + T(n, 200);
                                n = n.nextElementSibling;
                            }
                            sections.push({heading: T(h,150), level: parseInt(h.tagName[1]),
                                           id: A(h,'id'), preview: text.trim().slice(0,200)});
                        });

                        // Forms and inputs summary
                        const forms = Array.from(document.querySelectorAll('form')).map((f,i) => ({
                            i, action: A(f,'action'), method: A(f,'method')||'get',
                            inputs: Array.from(f.querySelectorAll('input,select,textarea')).map(el => ({
                                name: A(el,'name')||A(el,'id'), type: A(el,'type')||el.tagName.toLowerCase(),
                                placeholder: A(el,'placeholder'), label: labelFor(el), key: componentKey(el),
                                required: el.hasAttribute('required')
                            })).slice(0,15)
                        })).slice(0,10);

                        const lowcode_components = Array.from(document.querySelectorAll('.formio-component, [data-block], [data-widget], input, select, textarea, button'))
                            .map((el, i) => {
                                const control = ['INPUT','SELECT','TEXTAREA','BUTTON'].includes(el.tagName) ? el : el.querySelector('input,select,textarea,button');
                                const target = control || el;
                                const classes = A(el, 'class');
                                const typeClass = (classes.match(/formio-component-([a-zA-Z0-9_-]+)/) || [])[1] || '';
                                return {
                                    i,
                                    platform: /formio/i.test(classes) ? 'formio' : (/osui|outsystems/i.test(classes + ' ' + A(el, 'data-block') + ' ' + A(el, 'data-widget')) ? 'outsystems' : ''),
                                    label: labelFor(target),
                                    key: componentKey(target),
                                    type: typeClass || A(target,'type') || target.tagName.toLowerCase(),
                                    required: target.hasAttribute('required'),
                                    disabled: target.hasAttribute('disabled'),
                                };
                            })
                            .filter(c => c.label || c.key || c.platform)
                            .slice(0,80);

                        return {headings, tables, code, lists, images, key_values, sections, forms, lowcode_components};
                    }
                    """) or {}
                except Exception:
                    pass

                # SPA framework detection + shadow DOM
                spa_info = await page.evaluate("""
                () => {
                    const srcs = Array.from(document.querySelectorAll('script[src]'))
                        .map(s => s.src.toLowerCase()).join(' ');
                    const inline = Array.from(document.querySelectorAll('script:not([src])'))
                        .map(s => (s.textContent||'').slice(0,3000)).join(' ').toLowerCase();
                    const body = document.body ? document.body.innerHTML.slice(0,3000).toLowerCase() : '';

                    let framework = 'static';
                    if (document.querySelector('.formio, .formio-component') || srcs.includes('formio') || inline.includes('formio'))
                        framework = 'formio';
                    else if (document.querySelector('[data-block], [data-widget], [data-container], .osui, [class*="osui-"]')
                             || srcs.includes('outsystems') || inline.includes('outsystems') || inline.includes('__osvstate') || body.includes('outsystems-ui'))
                        framework = 'outsystems';
                    else if (document.getElementById('__next') || body.includes('__next_data__'))
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
                    network_requests=network_reqs,
                    page_metrics=page_metrics,
                    embedded_json=embedded_json,
                    json_ld=json_ld,
                    lazy_images_resolved=lazy_resolved,
                    dom_index=dom_index,
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
        """Scroll incrementally by viewport height to trigger lazy-load correctly."""
        try:
            viewport_h: int = await page.evaluate("window.innerHeight") or 800
        except Exception:
            viewport_h = 800

        pos = 0
        for _ in range(40):
            try:
                total = await page.evaluate("document.body.scrollHeight") or 0
                if pos >= total:
                    break
                pos = min(pos + viewport_h, total)
                await page.evaluate(f"window.scrollTo(0, {pos})")
                await asyncio.sleep(0.3)
            except Exception:
                break

        # Scroll back to top then to bottom — triggers any remaining lazy-loads
        try:
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.15)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
