"""
extractor.py — Extract metadata, links, images and interactive elements from
fetched HTML.  Also contains YouTube-specific extraction logic (no API key
needed).

YouTube strategy (priority order):
1. oEmbed API — title, author, thumbnail
2. ytInitialData JSON embedded in HTML — description, tags, views, date, duration
3. JSON-LD schema — fallback metadata
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from bs4 import BeautifulSoup


@dataclass
class PageMetadata:
    url: str
    title: str = ""
    description: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_type: str = ""
    canonical: str = ""
    lang: str = ""
    author: str = ""
    keywords: list[str] = field(default_factory=list)


@dataclass
class PageLinks:
    internal: list[dict] = field(default_factory=list)   # {"text": ..., "href": ...}
    external: list[dict] = field(default_factory=list)


@dataclass
class PageImages:
    items: list[dict] = field(default_factory=list)       # {"src": ..., "alt": ..., "title": ...}


@dataclass
class LayoutSection:
    """A region in the page layout."""
    tag: str                                # header | nav | main | aside | footer | section
    name: str                               # id or first class name
    heading: str = ""                       # text of the first h1-h4 within this region
    links: list[dict] = field(default_factory=list)   # [{"text", "href"}]
    text_preview: str = ""                 # first 200 chars of text content
    role: str = ""                          # aria-role if present


@dataclass
class PageLayout:
    """Page layout structure."""
    sections: list[LayoutSection] = field(default_factory=list)
    framework: str = "static"              # static | react | vue | angular | next.js | nuxt
    has_shadow_dom: bool = False            # True if Playwright detected shadow DOM
    spa_route: str = ""                    # hash/pushState route if SPA


@dataclass
class PageInteractives:
    """Interactive elements with full attributes for agent reference.

    Every item dict includes a `selector` field (CSS) that an agent can use
    to locate the element and trace back to the original DOM node.
    """
    buttons: list[dict] = field(default_factory=list)
    # {label, tag, type, id, name, classes, role, aria_label, disabled, selector}
    inputs: list[dict] = field(default_factory=list)
    # {type, name, id, placeholder, aria_label, required, value, selector}
    selects: list[dict] = field(default_factory=list)
    # {name, id, aria_label, options: [{value, label}], selector}
    forms: list[dict] = field(default_factory=list)
    # {action, method, id, name, enctype, fields: [name,...], selector}
    links: list[dict] = field(default_factory=list)
    # {text, href, id, classes, role, aria_label, rel, target, selector}
    nav_links: list[dict] = field(default_factory=list)
    # nav-scoped subset of links


@dataclass
class ExtractResult:
    metadata: PageMetadata
    links: PageLinks
    images: PageImages
    iframes: list[dict] = field(default_factory=list)
    # iframes: [{"src", "type": youtube|spotify|maps|same_origin|cross_origin, "video_id"}]
    layout: Optional[PageLayout] = None
    interactives: Optional[PageInteractives] = None


class PageExtractor:
    """Extract metadata, links and images from HTML."""

    def extract(
        self,
        html: str,
        base_url: str,
        spa_framework: str = "static",
        has_shadow_dom: bool = False,
    ) -> ExtractResult:
        soup = BeautifulSoup(html, "lxml")
        layout = self._extract_layout(soup, base_url, spa_framework, has_shadow_dom)
        return ExtractResult(
            metadata=self._extract_metadata(soup, base_url),
            links=self._extract_links(soup, base_url),
            images=self._extract_images(soup, base_url),
            iframes=self._extract_iframes(soup, base_url),
            layout=layout,
            interactives=self._extract_interactives(soup),
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _extract_metadata(self, soup: BeautifulSoup, base_url: str) -> PageMetadata:
        def meta(name: str = None, prop: str = None) -> str:
            if name:
                tag = soup.find("meta", attrs={"name": name})
            elif prop:
                tag = soup.find("meta", attrs={"property": prop})
            else:
                return ""
            return (tag.get("content") or "").strip() if tag else ""

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        canonical_tag = soup.find("link", rel="canonical")
        canonical = canonical_tag.get("href", "") if canonical_tag else ""

        html_tag = soup.find("html")
        lang = html_tag.get("lang", "") if html_tag else ""

        keywords_raw = meta(name="keywords")
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

        return PageMetadata(
            url=base_url,
            title=title,
            description=meta(name="description"),
            og_title=meta(prop="og:title"),
            og_description=meta(prop="og:description"),
            og_image=meta(prop="og:image"),
            og_type=meta(prop="og:type"),
            canonical=canonical,
            lang=lang,
            author=meta(name="author"),
            keywords=keywords,
        )

    # ------------------------------------------------------------------
    # Links
    # ------------------------------------------------------------------

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> PageLinks:
        base_domain = urlparse(base_url).netloc
        internal, external = [], []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            abs_href = urljoin(base_url, href)
            text = a.get_text(strip=True) or ""
            entry = {"text": text, "href": abs_href}

            if urlparse(abs_href).netloc == base_domain:
                internal.append(entry)
            else:
                external.append(entry)

        # Deduplicate by href
        internal = list({d["href"]: d for d in internal}.values())
        external = list({d["href"]: d for d in external}.values())

        return PageLinks(internal=internal, external=external)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> PageImages:
        items = []
        seen = set()

        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            abs_src = urljoin(base_url, src.strip())
            if abs_src in seen:
                continue
            seen.add(abs_src)
            items.append({
                "src": abs_src,
                "alt": (img.get("alt") or "").strip(),
                "title": (img.get("title") or "").strip(),
                "width": img.get("width", ""),
                "height": img.get("height", ""),
            })

        return PageImages(items=items)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    # Semantic tags (high priority) + fallback div/section with clear id/class
    _LAYOUT_TAGS = ["header", "nav", "main", "article", "aside", "footer", "section"]
    _LAYOUT_DIV_ROLES = {
        "header": ["header", "site-header", "page-header", "topbar", "masthead"],
        "nav": ["nav", "navigation", "menu", "sidebar", "sidenav"],
        "main": ["main", "content", "main-content", "article", "body"],
        "aside": ["aside", "sidebar", "widget", "panel"],
        "footer": ["footer", "site-footer", "page-footer", "bottom"],
    }

    def _extract_layout(
        self,
        soup: BeautifulSoup,
        base_url: str,
        spa_framework: str = "static",
        has_shadow_dom: bool = False,
    ) -> PageLayout:
        """Analyse page layout: identify semantic regions and their content."""
        sections: list[LayoutSection] = []
        seen_tags: set = set()   # avoid duplicates

        # 1. Semantic HTML5 tags
        for tag_name in self._LAYOUT_TAGS:
            for el in soup.find_all(tag_name)[:4]:  # max 4 instances per type
                el_id = (el.get("id") or "").strip()
                el_classes = el.get("class") or []
                name = el_id or (" ".join(str(c) for c in el_classes[:2])) or tag_name
                key = f"{tag_name}#{name}"
                if key in seen_tags:
                    continue
                seen_tags.add(key)

                sections.append(self._build_section(el, tag_name, name, base_url))

        # 2. Fallback: <div> whose id/class matches a layout pattern
        for role, patterns in self._LAYOUT_DIV_ROLES.items():
            for div in soup.find_all("div", limit=50):
                div_id = (div.get("id") or "").lower()
                div_cls = " ".join(str(c) for c in (div.get("class") or [])).lower()
                if any(p in div_id or p in div_cls for p in patterns):
                    key = f"div#{div_id or div_cls[:20]}"
                    if key in seen_tags:
                        continue
                    seen_tags.add(key)
                    name = div_id or div_cls.split()[0]
                    sections.append(self._build_section(div, f"div.{role}", name, base_url))
                    break  # 1 fallback per role

        # 3. Detect framework from HTML
        framework = spa_framework if spa_framework != "static" else self._detect_framework(soup)

        return PageLayout(
            sections=sections,
            framework=framework,
            has_shadow_dom=has_shadow_dom,
        )

    def _build_section(
        self, el, tag: str, name: str, base_url: str
    ) -> LayoutSection:
        # First heading within the region
        h_tag = el.find(["h1", "h2", "h3", "h4"])
        heading = h_tag.get_text(strip=True)[:100] if h_tag else ""

        # Links within the region (max 15)
        links = []
        seen_hrefs: set = set()
        for a in el.find_all("a", href=True)[:20]:
            text = a.get_text(strip=True)[:60]
            href = urljoin(base_url, a["href"])
            if text and href not in seen_hrefs and not href.startswith("javascript:"):
                seen_hrefs.add(href)
                links.append({"text": text, "href": href})
            if len(links) >= 15:
                break

        # Text preview
        text_preview = " ".join(el.stripped_strings)[:200]

        # ARIA role
        role = (el.get("role") or "").strip()

        return LayoutSection(
            tag=tag,
            name=name,
            heading=heading,
            links=links,
            text_preview=text_preview,
            role=role,
        )

    def _detect_framework(self, soup: BeautifulSoup) -> str:
        """Detect JS framework from static HTML (script src, data attrs, meta)."""
        # Script sources
        srcs = " ".join(s.get("src", "") for s in soup.find_all("script", src=True)).lower()
        # Inline script text (limited to avoid slowdown)
        inline = " ".join(
            (s.string or "") for s in soup.find_all("script") if s.string
        )[:5000].lower()

        if soup.find(id="__next") or "__next_data__" in inline or "next.js" in srcs:
            return "next.js"
        if soup.find(id="__nuxt") or "__nuxt__" in inline or "nuxt" in srcs:
            return "nuxt"
        if soup.find(attrs={"ng-version": True}) or "angular" in srcs:
            return "angular"
        if soup.find(attrs={"data-v-app": True}) or "vue" in srcs:
            return "vue"
        if (soup.find(id="root") or soup.find(id="app")) and ("react" in srcs or "react" in inline):
            return "react"
        if "react" in srcs or "react" in inline:
            return "react"
        return "static"

    # ------------------------------------------------------------------
    # Iframes
    # ------------------------------------------------------------------

    def _extract_iframes(self, soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extract and classify all iframe/frame elements on the page."""
        base_domain = urlparse(base_url).netloc
        iframes = []

        for tag in soup.find_all(["iframe", "frame"]):
            src = tag.get("src", "").strip()
            if not src or src.startswith(("about:", "javascript:", "data:")):
                continue

            abs_src = urljoin(base_url, src)
            host = urlparse(abs_src).netloc.lower()

            entry = {
                "src": abs_src,
                "type": "other",
                "video_id": "",
                "title": (tag.get("title") or tag.get("name") or "").strip(),
                "width": tag.get("width", ""),
                "height": tag.get("height", ""),
            }

            if re.search(r"youtube(?:-nocookie)?\.com/embed/", abs_src):
                m = re.search(r"/embed/([A-Za-z0-9_-]{11})", abs_src)
                entry["type"] = "youtube"
                entry["video_id"] = m.group(1) if m else ""
            elif re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", abs_src):
                m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", abs_src)
                entry["type"] = "youtube"
                entry["video_id"] = m.group(1) if m else ""
            elif "open.spotify.com/embed/" in abs_src:
                entry["type"] = "spotify"
            elif "google.com/maps/embed" in abs_src or "maps.google.com" in abs_src:
                entry["type"] = "maps"
            elif not host or host == base_domain:
                entry["type"] = "same_origin"
            else:
                entry["type"] = "cross_origin"

            iframes.append(entry)

        return iframes

    # ------------------------------------------------------------------
    # Interactive elements
    # ------------------------------------------------------------------

    def _extract_interactives(self, soup: BeautifulSoup) -> PageInteractives:
        """Extract interactive elements with full attributes and CSS selectors."""
        result = PageInteractives()
        seen_btns: set[str] = set()

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_tags = soup.find_all(["button", "input"])
        role_btns = soup.find_all(attrs={"role": "button"})
        for el in btn_tags + role_btns:
            itype = (el.get("type") or "").lower()
            if el.name == "input" and itype not in ("submit", "button", "reset", "image"):
                continue
            label = (
                el.get_text(strip=True)
                or (el.get("value") or "").strip()
                or (el.get("aria-label") or "").strip()
                or (el.get("title") or "").strip()
            )
            if not label or len(label) >= 120:
                continue
            key = label.lower()
            if key in seen_btns:
                continue
            seen_btns.add(key)
            result.buttons.append({
                "label": label,
                "tag": el.name,
                "type": itype or ("button" if el.name == "button" else ""),
                "id": (el.get("id") or "").strip(),
                "name": (el.get("name") or "").strip(),
                "classes": " ".join(el.get("class") or [])[:80],
                "role": (el.get("role") or "").strip(),
                "aria_label": (el.get("aria-label") or "").strip(),
                "disabled": el.has_attr("disabled"),
                "selector": self._css_selector(el),
            })
            if len(result.buttons) >= 40:
                break

        # ── Inputs ───────────────────────────────────────────────────────────
        text_types = {"text", "email", "search", "password", "tel", "url",
                      "number", "date", "time", "datetime-local", ""}
        for inp in soup.find_all("input"):
            itype = (inp.get("type") or "").lower()
            if itype not in text_types:
                continue
            result.inputs.append({
                "type": itype or "text",
                "name": (inp.get("name") or "").strip(),
                "id": (inp.get("id") or "").strip(),
                "placeholder": (inp.get("placeholder") or "").strip(),
                "aria_label": (inp.get("aria-label") or "").strip(),
                "required": inp.has_attr("required"),
                "value": (inp.get("value") or "").strip()[:80],
                "selector": self._css_selector(inp),
            })

        # Textareas
        for ta in soup.find_all("textarea"):
            result.inputs.append({
                "type": "textarea",
                "name": (ta.get("name") or "").strip(),
                "id": (ta.get("id") or "").strip(),
                "placeholder": (ta.get("placeholder") or "").strip(),
                "aria_label": (ta.get("aria-label") or "").strip(),
                "required": ta.has_attr("required"),
                "value": "",
                "selector": self._css_selector(ta),
            })

        # ── Selects ──────────────────────────────────────────────────────────
        for sel in soup.find_all("select"):
            options = []
            for o in sel.find_all("option"):
                opt_text = o.get_text(strip=True)
                opt_val = (o.get("value") or "").strip()
                if opt_text:
                    options.append({"value": opt_val, "label": opt_text})
            result.selects.append({
                "name": (sel.get("name") or "").strip(),
                "id": (sel.get("id") or "").strip(),
                "aria_label": (sel.get("aria-label") or "").strip(),
                "options": options[:15],
                "selector": self._css_selector(sel),
            })

        # ── Forms ────────────────────────────────────────────────────────────
        for form in soup.find_all("form"):
            fields = []
            for child in form.find_all(["input", "textarea", "select"]):
                fname = (child.get("name") or child.get("id") or "").strip()
                ftype = (child.get("type") or child.name or "").lower()
                if fname:
                    fields.append({"name": fname, "type": ftype})
            result.forms.append({
                "action": (form.get("action") or "").strip(),
                "method": (form.get("method") or "get").upper(),
                "id": (form.get("id") or "").strip(),
                "name": (form.get("name") or "").strip(),
                "enctype": (form.get("enctype") or "").strip(),
                "fields": fields[:15],
                "selector": self._css_selector(form),
            })

        # ── Links (all <a>) ───────────────────────────────────────────────────
        seen_hrefs: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            text = a.get_text(strip=True)[:100]
            result.links.append({
                "text": text,
                "href": href,
                "id": (a.get("id") or "").strip(),
                "classes": " ".join(a.get("class") or [])[:80],
                "role": (a.get("role") or "").strip(),
                "aria_label": (a.get("aria-label") or "").strip(),
                "rel": " ".join(a.get("rel") or []),
                "target": (a.get("target") or "").strip(),
                "selector": self._css_selector(a),
            })
            if len(result.links) >= 100:
                break

        # ── Nav links (subset from <nav>/<header>) ────────────────────────────
        seen_nav_hrefs: set[str] = set()
        for container in soup.find_all(["nav", "header"]):
            for a in container.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href or href in seen_nav_hrefs:
                    continue
                seen_nav_hrefs.add(href)
                text = a.get_text(strip=True)[:80]
                if not text:
                    continue
                result.nav_links.append({
                    "text": text,
                    "href": href,
                    "id": (a.get("id") or "").strip(),
                    "aria_label": (a.get("aria-label") or "").strip(),
                    "selector": self._css_selector(a),
                })
                if len(result.nav_links) >= 40:
                    break

        return result

    @staticmethod
    def _css_selector(el) -> str:
        """Build a best-effort unique CSS selector for a BeautifulSoup tag."""
        parts = [el.name]
        eid = (el.get("id") or "").strip()
        if eid:
            # ID is unique — shortest possible selector
            return f"#{eid}"
        name = (el.get("name") or "").strip()
        if name:
            parts.append(f'[name="{name}"]')
        itype = (el.get("type") or "").strip()
        if itype:
            parts.append(f'[type="{itype}"]')
        aria = (el.get("aria-label") or "").strip()
        if aria:
            parts.append(f'[aria-label="{aria}"]')
        classes = [c for c in (el.get("class") or []) if c and not c.startswith(("css-", "_", "sc-"))]
        if classes:
            parts.append("." + ".".join(classes[:3]))
        return "".join(parts)

    # ------------------------------------------------------------------
    # Format as Markdown
    # ------------------------------------------------------------------

    def to_markdown(self, result: ExtractResult, max_links: int = 20, max_images: int = 10) -> str:
        md = result.metadata
        lines = [
            "## 📋 Metadata",
            f"- **Title:** {md.title or md.og_title}",
            f"- **Description:** {md.description or md.og_description}",
            f"- **URL:** {md.url}",
            f"- **Language:** {md.lang}",
            f"- **Author:** {md.author}",
            f"- **Keywords:** {', '.join(md.keywords) if md.keywords else '—'}",
        ]

        if md.og_image:
            lines.append(f"- **OG Image:** {md.og_image}")

        # External links
        lines += ["", "## 🔗 External Links"]
        ext = result.links.external[:max_links]
        if ext:
            for lnk in ext:
                lines.append(f"- [{lnk['text'] or lnk['href']}]({lnk['href']})")
        else:
            lines.append("_(none)_")

        # Images
        lines += ["", "## 🖼️ Images"]
        imgs = result.images.items[:max_images]
        if imgs:
            for img in imgs:
                alt = img["alt"] or img["title"] or "image"
                lines.append(f"- ![{alt}]({img['src']})")
        else:
            lines.append("_(none)_")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# YouTube extraction (no API key required)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RelatedVideo:
    video_id: str
    title: str
    channel: str = ""
    duration: str = ""
    view_count: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class YouTubeInfo:
    video_id: str
    url: str
    title: str = ""
    author: str = ""
    channel_url: str = ""
    thumbnail: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    view_count: str = ""
    like_count: str = ""
    upload_date: str = ""
    duration: str = ""
    category: str = ""
    related_videos: list["RelatedVideo"] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Format as Markdown for Obsidian."""
        lines = []

        if self.thumbnail:
            lines.append(f"![Thumbnail]({self.thumbnail})\n")

        meta_rows = [
            ("📺 Channel", f"[[{self.author}]]" if self.author else ""),
            ("📅 Upload date", self.upload_date),
            ("👁️ Views", self.view_count),
            ("👍 Likes", self.like_count),
            ("⏱️ Duration", self.duration),
            ("🏷️ Category", self.category),
        ]
        for label, val in meta_rows:
            if val:
                lines.append(f"**{label}:** {val}  ")

        if self.description:
            lines.append("\n### Description\n")
            lines.append(self.description[:2000])
            if len(self.description) > 2000:
                lines.append("\n_(description truncated)_")

        if self.related_videos:
            lines.append("\n## 📋 Related videos\n")
            lines.append("| Video | Channel | Duration | Views |")
            lines.append("|-------|---------|----------|-------|")
            for rv in self.related_videos:
                title_link = f"[{rv.title}]({rv.url})" if rv.title else rv.url
                lines.append(f"| {title_link} | {rv.channel} | {rv.duration} | {rv.view_count} |")

        return "\n".join(lines)

    def get_entities(self) -> list[str]:
        """Entities for creating WikiLinks."""
        ents = []
        if self.author:
            ents.append(self.author)
        if self.category:
            ents.append(self.category)
        ents.extend(self.tags[:10])
        ents.extend(self._extract_names_from_title())
        for rv in self.related_videos[:10]:
            if rv.channel and rv.channel != self.author:
                ents.append(rv.channel)
        return list(dict.fromkeys(e for e in ents if e and len(e) >= 3))

    def _extract_names_from_title(self) -> list[str]:
        """Extract capitalised word groups from title as entities."""
        if not self.title:
            return []
        parts = re.findall(
            r"[A-Z\u00c0-\u1ef9][a-z\u00e0-\u1ef9]+(?:\s[A-Z\u00c0-\u1ef9][a-z\u00e0-\u1ef9]+)+",
            self.title,
        )
        return parts


class YouTubeExtractor:
    """
    Extract YouTube video data from a URL and/or fetched HTML.

    Example:
        yt = YouTubeExtractor()
        info = yt.extract("https://www.youtube.com/watch?v=...")
        markdown = info.to_markdown()
    """

    OEMBED_URL = "https://www.youtube.com/oembed"

    def extract(self, url: str, html: str = "") -> Optional[YouTubeInfo]:
        """Extract all video information. html is optional."""
        video_id = self._extract_video_id(url)
        if not video_id:
            return None

        info = YouTubeInfo(video_id=video_id, url=url)

        # 1. oEmbed — title, author, thumbnail
        self._fetch_oembed(url, info)

        # 2. ytInitialData from HTML (if provided)
        if html:
            self._parse_initial_data(html, info)

        # 3. JSON-LD fallback
        if html and not info.description:
            self._parse_json_ld(html, info)

        return info

    # ── oEmbed ─────────────────────────────────────────────────────────────

    def _fetch_oembed(self, url: str, info: YouTubeInfo):
        try:
            resp = httpx.get(
                self.OEMBED_URL,
                params={"url": url, "format": "json"},
                timeout=10.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                info.title = info.title or data.get("title", "")
                info.author = info.author or data.get("author_name", "")
                info.channel_url = info.channel_url or data.get("author_url", "")
                info.thumbnail = info.thumbnail or data.get("thumbnail_url", "")
        except Exception:
            pass

    # ── ytInitialData ───────────────────────────────────────────────────────

    def _parse_initial_data(self, html: str, info: YouTubeInfo):
        """Parse ytInitialData JSON from HTML to get description, views, tags..."""
        try:
            m = re.search(r"var ytInitialData\s*=\s*(\{.+?\});\s*(?:var |</script>)", html, re.DOTALL)
            if not m:
                m = re.search(r"ytInitialData\s*=\s*(\{.+?\});", html[:500000], re.DOTALL)
            if not m:
                return
            data = json.loads(m.group(1))
            self._extract_from_initial_data(data, info)
        except Exception:
            pass

    def _extract_from_initial_data(self, data: dict, info: YouTubeInfo):
        try:
            contents = (
                data.get("contents", {})
                .get("twoColumnWatchNextResults", {})
                .get("results", {})
                .get("results", {})
                .get("contents", [])
            )

            for item in contents:
                pir = item.get("videoPrimaryInfoRenderer", {})
                if pir:
                    title_runs = pir.get("title", {}).get("runs", [])
                    if title_runs and not info.title:
                        info.title = "".join(r.get("text", "") for r in title_runs)

                    vc = pir.get("viewCount", {}).get("videoViewCountRenderer", {})
                    if not info.view_count:
                        info.view_count = (
                            vc.get("shortViewCount", {}).get("simpleText", "")
                            or vc.get("viewCount", {}).get("simpleText", "")
                        )

                    date_text = pir.get("dateText", {}).get("simpleText", "")
                    if date_text and not info.upload_date:
                        info.upload_date = date_text

                    for btn in pir.get("videoActions", {}).get("menuRenderer", {}).get("topLevelButtons", []):
                        seg = btn.get("segmentedLikeDislikeButtonViewModel", {})
                        like_btn = seg.get("likeButtonViewModel", {}).get("likeButtonViewModel", {})
                        like_text = (
                            like_btn.get("toggleButtonViewModel", {})
                            .get("toggleButtonViewModel", {})
                            .get("defaultButtonViewModel", {})
                            .get("buttonViewModel", {})
                            .get("title", "")
                        )
                        if like_text and not info.like_count:
                            info.like_count = like_text

                sir = item.get("videoSecondaryInfoRenderer", {})
                if sir:
                    desc = sir.get("attributedDescription", {}) or sir.get("description", {})
                    if not info.description:
                        desc_content = desc.get("content", "")
                        if not desc_content:
                            runs = desc.get("runs", [])
                            desc_content = "".join(r.get("text", "") for r in runs)
                        info.description = desc_content.strip()

                    channel = sir.get("owner", {}).get("videoOwnerRenderer", {})
                    if channel and not info.author:
                        cr = channel.get("title", {}).get("runs", [])
                        info.author = "".join(r.get("text", "") for r in cr)

        except Exception:
            pass

        # Related videos from secondaryResults
        try:
            secondary_results = (
                data.get("contents", {})
                .get("twoColumnWatchNextResults", {})
                .get("secondaryResults", {})
                .get("secondaryResults", {})
                .get("results", [])
            )
            flat_items = []
            for item in secondary_results:
                if "itemSectionRenderer" in item:
                    flat_items.extend(item["itemSectionRenderer"].get("contents", []))
                else:
                    flat_items.append(item)

            for item in flat_items:
                vid_id = title_text = channel_name = vc_text = dur_text = ""

                lvm = item.get("lockupViewModel", {})
                if lvm:
                    vid_id = lvm.get("contentId", "")
                    lmeta = lvm.get("metadata", {}).get("lockupMetadataViewModel", {})
                    title_text = lmeta.get("title", {}).get("content", "")
                    cmeta = lmeta.get("metadata", {}).get("contentMetadataViewModel", {})
                    rows = cmeta.get("metadataRows", [])
                    if rows:
                        parts0 = rows[0].get("metadataParts", [])
                        channel_name = parts0[0].get("text", {}).get("content", "") if parts0 else ""
                    if len(rows) > 1:
                        parts1 = rows[1].get("metadataParts", [])
                        vc_text = parts1[0].get("text", {}).get("content", "") if parts1 else ""
                    for overlay in (
                        lvm.get("contentImage", {})
                        .get("thumbnailViewModel", {})
                        .get("overlays", [])
                    ):
                        badge = (
                            overlay.get("thumbnailBottomOverlayViewModel", {})
                            .get("badges", [{}])[0]
                            .get("thumbnailBadgeViewModel", {})
                        )
                        dur_text = badge.get("text", "")
                        if dur_text:
                            break
                else:
                    cvr = item.get("compactVideoRenderer", {})
                    if not cvr:
                        continue
                    vid_id = cvr.get("videoId", "")
                    title_runs = cvr.get("title", {}).get("runs", [])
                    title_text = cvr.get("title", {}).get("simpleText", "") or \
                                 "".join(r.get("text", "") for r in title_runs)
                    byline_runs = cvr.get("shortBylineText", {}).get("runs", [])
                    channel_name = "".join(r.get("text", "") for r in byline_runs)
                    vc_text = cvr.get("shortViewCountText", {}).get("simpleText", "") or \
                              "".join(r.get("text", "") for r in cvr.get("shortViewCountText", {}).get("runs", []))
                    for overlay in cvr.get("thumbnailOverlays", []):
                        tos = overlay.get("thumbnailOverlayTimeStatusRenderer", {})
                        dur_text = tos.get("text", {}).get("simpleText", "") or \
                                   "".join(r.get("text", "") for r in tos.get("text", {}).get("runs", []))
                        if dur_text:
                            break

                if vid_id and title_text:
                    info.related_videos.append(RelatedVideo(
                        video_id=vid_id,
                        title=title_text,
                        channel=channel_name,
                        duration=dur_text,
                        view_count=vc_text,
                    ))
                if len(info.related_videos) >= 10:
                    break
        except Exception:
            pass

        # Tags from microformat
        try:
            mf = data.get("microformat", {}).get("playerMicroformatRenderer", {})
            if mf:
                if not info.tags:
                    info.tags = mf.get("keywords", [])[:15]
                if not info.category:
                    info.category = mf.get("category", "")
                if not info.upload_date:
                    info.upload_date = mf.get("publishDate", "") or mf.get("uploadDate", "")
                if not info.duration:
                    secs = mf.get("lengthSeconds", "")
                    if secs:
                        s = int(secs)
                        info.duration = (
                            f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
                            if s >= 3600
                            else f"{s // 60}:{s % 60:02d}"
                        )
                if not info.description:
                    info.description = (
                        mf.get("description", {}).get("simpleText", "")
                        or mf.get("description", {}).get("content", "")
                    )
        except Exception:
            pass

    # ── JSON-LD ─────────────────────────────────────────────────────────────

    def _parse_json_ld(self, html: str, info: YouTubeInfo):
        try:
            for m in re.finditer(
                r'<script[^>]+type="application/ld\+json"[^>]*>([\s\S]*?)</script>',
                html, re.IGNORECASE
            ):
                data = json.loads(m.group(1))
                if isinstance(data, list):
                    data = next((d for d in data if d.get("@type") == "VideoObject"), {})
                if data.get("@type") == "VideoObject":
                    info.title = info.title or data.get("name", "")
                    info.description = info.description or data.get("description", "")
                    info.upload_date = info.upload_date or data.get("uploadDate", "")
                    info.duration = info.duration or data.get("duration", "")
                    info.thumbnail = info.thumbnail or (
                        data.get("thumbnailUrl", [None])[0]
                        if isinstance(data.get("thumbnailUrl"), list)
                        else data.get("thumbnailUrl", "")
                    )
                    author = data.get("author", {})
                    if isinstance(author, dict):
                        info.author = info.author or author.get("name", "")
                    break
        except Exception:
            pass

    # ── Helper ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        parsed = urlparse(url)
        if parsed.netloc in ("youtu.be",):
            return parsed.path.lstrip("/").split("/")[0] or None
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
