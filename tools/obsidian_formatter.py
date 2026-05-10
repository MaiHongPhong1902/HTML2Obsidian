"""
obsidian_formatter.py — Convert pipeline result into an Obsidian note.

Output:
- YAML frontmatter (url, title, tags, date, domain...)
- Content with [[WikiLinks]] for key entities
- ## Relationships section listing related nodes
- ## References section with external links
- Compatible with Obsidian Graph View

WikiLink strategy:
1. spaCy NER (if available) → extract people, places, organisations, works
2. Fallback: extract from headings + internal links of the original page
3. Always WikiLink: page title + section headings
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import unquote, urlparse


@dataclass
class ObsidianNote:
    frontmatter: dict
    body: str

    def render(self) -> str:
        yaml_lines = ["---"]
        for k, v in self.frontmatter.items():
            if isinstance(v, list):
                if v:
                    yaml_lines.append(f"{k}:")
                    for item in v:
                        yaml_lines.append(f"  - {item}")
                else:
                    yaml_lines.append(f"{k}: []")
            elif isinstance(v, str) and ("\n" in v or ":" in v):
                yaml_lines.append(f'{k}: "{v}"')
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")
        return "\n".join(yaml_lines) + "\n\n" + self.body


@dataclass
class SiteMapConfig:
    style: str = "tree"              # tree | table | both
    max_internal_links: int = 120
    max_external_links: int = 30
    max_depth: int = 3

    def __post_init__(self):
        if self.style not in {"tree", "table", "both"}:
            raise ValueError("site_map_style must be one of: tree, table, both")
        self.max_internal_links = max(1, int(self.max_internal_links))
        self.max_external_links = max(0, int(self.max_external_links))
        self.max_depth = max(1, int(self.max_depth))


class ObsidianFormatter:
    """
    Convert PipelineResult / clean markdown → Obsidian note with WikiLinks.

    Example:
        formatter = ObsidianFormatter()
        note = formatter.format(pipeline_result)
        Path("Python.md").write_text(note.render())
    """

    # Auto tags by domain
    DOMAIN_TAGS = {
        "wikipedia.org": ["wikipedia", "reference"],
        "github.com": ["github", "code", "opensource"],
        "youtube.com": ["youtube", "video", "media"],
        "canva.com": ["canva", "design", "tool"],
        "arxiv.org": ["arxiv", "research", "paper"],
        "medium.com": ["medium", "article", "blog"],
        "reddit.com": ["reddit", "community"],
        "stackoverflow.com": ["stackoverflow", "programming", "qa"],
        "twitter.com": ["twitter", "social"],
        "x.com": ["twitter", "social"],
    }

    MAX_AUTO_TAGS = 12

    TAG_BLACKLIST = {
        "www", "http", "https", "html", "htm", "php", "asp", "aspx",
        "index", "default", "home", "main", "page", "pages", "latest",
        "master", "raw", "edit", "view", "download", "amp",
        "object", "profile",
        "en", "vi", "fr", "de", "es", "pt", "jp", "cn", "kr",
    }

    CONTENT_TAG_HINTS = {
        "documentation": ["docs", "documentation", "developer docs"],
        "guide": ["guide", "guides", "tutorial", "walkthrough", "how to"],
        "api": ["api", "sdk", "endpoint"],
        "reference": ["reference", "specification", "cli reference"],
        "repository": ["repository", "repo", "source code"],
        "release-notes": ["release notes", "changelog", "what's new"],
        "faq": ["faq", "frequently asked questions"],
        "pricing": ["pricing", "plans", "billing"],
        "sponsorship": ["sponsor", "sponsors", "funding"],
        "blog": ["blog", "newsletter"],
    }

    # UI/navigation noise — should not become WikiLinks
    NAV_BLACKLIST = {
        "log in", "log out", "sign in", "sign up", "create account",
        "search", "donate", "help", "about", "contact", "about wikipedia",
        "contact wikipedia", "contact us", "main page", "contents",
        "current events", "random article", "community portal",
        "recent changes", "upload file", "special pages", "watchlist",
        "learn to edit", "download as pdf", "printable version",
        "get shortened url", "cite this page", "read", "edit", "talk",
        "see also", "further reading", "references", "notes", "external links",
        "top", "footer", "navigation", "sidebar", "menu", "home",
    }

    # Noise patterns to drop when building WikiLinks
    NOISE_PATTERNS = [
        r"^\d+$",                          # Pure numbers
        r"^(the|a|an|of|in|on|at|to|for|with|by|from|and|or|but|is|was|are|were)$",
        r"^.{1,2}$",                       # Too short
        r"https?://",                       # URLs
        r"^\W+$",                           # Only special characters
    ]

    def __init__(self, use_spacy: bool = True, min_entity_len: int = 3):
        self.use_spacy = use_spacy
        self.min_entity_len = min_entity_len
        self._nlp = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(
        self,
        pipeline_result,
        note_title: Optional[str] = None,
        from_url: str = "",
        from_title: str = "",
    ) -> ObsidianNote:
        """Format PipelineResult into ObsidianNote."""
        from .pipeline import PipelineResult
        result: PipelineResult = pipeline_result

        domain = urlparse(result.url).netloc.replace("www.", "")

        # ── Domain-specific dispatch ────────────────────────────────────────
        if "youtube.com" in domain or "youtu.be" in domain:
            return self._format_youtube(result, note_title, from_url=from_url, from_title=from_title)

        title = note_title or self._extract_title(result)
        tags = self._build_tags(domain, result)

        # Extract entities from content
        entities = self._extract_entities(result.clean_markdown, result)

        # Build body
        body = self._build_body(result, title, entities, from_url=from_url, from_title=from_title)

        frontmatter = {
            "title": title,
            "url": result.url,
            "domain": domain,
            "fetched": datetime.now().strftime("%Y-%m-%d"),
            "tags": tags,
            "entities": sorted(entities)[:30],  # Top 30 entity
        }
        if from_url:
            frontmatter["from_url"] = from_url
        if result.extract and result.extract.layout:
            frontmatter["framework"] = result.extract.layout.framework
            frontmatter["has_shadow_dom"] = result.extract.layout.has_shadow_dom
        if result.extract and getattr(result.extract, "lowcode", None) and result.extract.lowcode.platform:
            frontmatter["lowcode_platform"] = result.extract.lowcode.platform
            frontmatter["lowcode_components_count"] = len(result.extract.lowcode.components)

        return ObsidianNote(frontmatter=frontmatter, body=body)

    def format_agent_context(
        self,
        pipeline_result,
        note_title: Optional[str] = None,
        max_excerpt_chars: int = 2200,
    ) -> str:
        """Build compact context optimized for agent consumption."""
        result = pipeline_result
        title = note_title or self._extract_title(result)
        lines = [f"# Agent Context: {title}", ""]
        lines.extend(self._build_agent_snapshot_lines(result))

        content_outline = self._extract_content_outline(result.clean_markdown)
        if content_outline:
            lines.extend(["", "## Content Outline", ""])
            for heading in content_outline[:8]:
                lines.append(f"- {heading}")

        excerpt = self._extract_content_excerpt(result.clean_markdown, max_chars=max_excerpt_chars)
        if excerpt:
            lines.extend(["", "## Key Excerpt", "", excerpt])

        return "\n".join(lines).strip()

    def build_site_map(
        self,
        pipeline_result,
        note_title: Optional[str] = None,
        site_map_config: Optional[SiteMapConfig] = None,
    ) -> ObsidianNote:
        """Build a dedicated site map note from a pipeline result."""
        result = pipeline_result
        domain = urlparse(result.url).netloc.replace("www.", "")
        source_title = note_title or self._extract_title(result)
        config = site_map_config or SiteMapConfig()
        nav_links = self._collect_nav_links(
            result,
            domain,
            max_internal=config.max_internal_links,
            max_external=config.max_external_links,
        )
        return self._build_map_note(
            result,
            domain,
            nav_links,
            source_title,
            site_map_config=config,
        )

    # ------------------------------------------------------------------
    # YouTube-specific formatter
    # ------------------------------------------------------------------

    def _format_youtube(
        self,
        result,
        note_title: Optional[str] = None,
        from_url: str = "",
        from_title: str = "",
    ) -> ObsidianNote:
        from .extractor import YouTubeExtractor

        yt = YouTubeExtractor()
        # Pass raw HTML (if available) to parse ytInitialData
        html = getattr(result, "_html", "") or ""
        if not html and result.extract:
            pass

        info = yt.extract(result.url, html)

        if info is None:
            # Fallback to generic formatter if video ID not recognised
            title = note_title or self._extract_title(result)
            domain = "youtube.com"
            entities = self._extract_entities(result.clean_markdown, result)
            body = self._build_body(result, title, entities)
            return ObsidianNote(
                frontmatter={"title": title, "url": result.url, "domain": domain,
                             "fetched": self._today(), "tags": ["web-clip", "youtube", "video"],
                             "entities": []},
                body=body,
            )

        title = note_title or info.title or "YouTube Video"
        entities = info.get_entities()

        # Build body
        content_md = info.to_markdown()
        body_lines = [
            f"# {title}\n",
            content_md,
            "",
        ]

        # Interactive elements from rendered HTML (buttons, inputs on the page)
        if result.extract and result.extract.interactives:
            iv = result.extract.interactives
            has_any = iv.buttons or iv.inputs or iv.nav_links
            if has_any:
                body_lines.append("## 🖱️ Interactive Elements\n")
                if iv.buttons:
                    body_lines.append("**Buttons:**")
                    body_lines.append("| Label | tag | type | id | selector |")
                    body_lines.append("|-------|-----|------|----|----------|")
                    for b in iv.buttons:
                        raw = (b["label"] or "—")[:50]
                        label = f"[[{raw}]]" if len(raw) >= 3 and not self._is_noise(raw) else raw
                        label = label.replace("|", "｜")
                        disabled = " _(disabled)_" if b["disabled"] else ""
                        body_lines.append(
                            f"| {label}{disabled} | `{b['tag']}` | `{b['type'] or '—'}` "
                            f"| `{b['id'] or '—'}` | `{b['selector'][:60]}` |"
                        )
                    body_lines.append("")
                if iv.inputs:
                    body_lines.append("**Input fields:**")
                    body_lines.append("| type | name / id | placeholder | aria-label | selector |")
                    body_lines.append("|------|-----------|-------------|------------|----------|")
                    for inp in iv.inputs:
                        name = inp["name"] or inp["id"] or "—"
                        ph = (inp["placeholder"] or "—").replace("|", "｜")[:40]
                        al = (inp["aria_label"] or "—").replace("|", "｜")[:40]
                        body_lines.append(
                            f"| `{inp['type']}` | `{name}` | {ph} | {al} | `{inp['selector'][:60]}` |"
                        )
                    body_lines.append("")

        body_lines += [
            "## 🔗 Relationships\n",
        ]

        if entities:
            for e in entities:
                if not self._is_noise(e):
                    body_lines.append(f"- [[{e}]]")
        else:
            body_lines.append("_(no entities extracted)_")

        body_lines += [
            "",
            f"---\n> 🎬 Video: [{result.url}]({result.url})",
        ]

        tags_base: list[str] = []
        for tag in ["web-clip", "youtube", "video", "media"]:
            self._append_tag(tags_base, tag)
        if info.category:
            self._append_tag(tags_base, info.category)
        for tag in info.tags[:6]:
            self._append_tag(tags_base, tag)

        frontmatter = {
            "title": title,
            "url": result.url,
            "video_id": info.video_id,
            "channel": info.author,
            "domain": "youtube.com",
            "fetched": self._today(),
            "upload_date": info.upload_date,
            "duration": info.duration,
            "tags": tags_base,
            "entities": [e for e in entities if not self._is_noise(e)][:20],
        }

        return ObsidianNote(frontmatter=frontmatter, body="\n".join(body_lines))

    @staticmethod
    def _today() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d")

    def format_raw(
        self,
        clean_markdown: str,
        url: str,
        title: str = "",
        extract_result=None,
        note_title: Optional[str] = None,
    ) -> ObsidianNote:
        """Format from raw markdown (no PipelineResult required)."""
        domain = urlparse(url).netloc.replace("www.", "")
        tags = self._build_tags(
            domain,
            None,
            url=url,
            title=effective_title,
            clean_markdown=clean_markdown,
            extract_result=extract_result,
        )
        entities = self._extract_entities(clean_markdown, None)

        # Build internal links from extract_result if available
        internal_links = []
        if extract_result:
            internal_links = [
                lnk["text"] for lnk in extract_result.links.internal[:50]
                if lnk.get("text") and len(lnk["text"]) >= self.min_entity_len
            ]

        effective_title = note_title or title or domain
        body = self._build_body_raw(clean_markdown, effective_title, entities, internal_links, url, extract_result)

        frontmatter = {
            "title": effective_title,
            "url": url,
            "domain": domain,
            "fetched": datetime.now().strftime("%Y-%m-%d"),
            "tags": tags,
            "entities": sorted(entities)[:30],
        }
        if extract_result and getattr(extract_result, "lowcode", None) and extract_result.lowcode.platform:
            frontmatter["lowcode_platform"] = extract_result.lowcode.platform
            frontmatter["lowcode_components_count"] = len(extract_result.lowcode.components)

        return ObsidianNote(frontmatter=frontmatter, body=body)

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------

    def _extract_entities(self, text: str, result=None) -> list[str]:
        entities = set()

        # 1. spaCy NER
        if self.use_spacy:
            spacy_ents = self._extract_spacy(text)
            entities.update(spacy_ents)

        # 2. Headings → WikiLink candidates
        heading_ents = self._extract_from_headings(text)
        entities.update(heading_ents)

        # 3. Internal links from the original page
        if result and hasattr(result, "extract") and result.extract:
            for lnk in result.extract.links.internal[:50]:
                txt = lnk.get("text", "").strip()
                if txt and len(txt) >= self.min_entity_len and not self._is_noise(txt):
                    entities.add(txt)

        # Filter noise
        return [e for e in entities if not self._is_noise(e)]

    def _extract_spacy(self, text: str) -> list[str]:
        """Extract entities via spaCy (PERSON, ORG, GPE, WORK_OF_ART, EVENT)."""
        try:
            import spacy
            if self._nlp is None:
                # Try loading models in priority order
                for model in ["vi_core_news_lg", "vi_core_news_sm", "en_core_web_sm", "en_core_web_md"]:
                    try:
                        self._nlp = spacy.load(model)
                        break
                    except OSError:
                        continue

            if self._nlp is None:
                return []

            # Limit text size to avoid slowdowns
            doc = self._nlp(text[:10000])
            target_labels = {"PERSON", "PER", "ORG", "GPE", "LOC", "WORK_OF_ART", "EVENT", "PRODUCT", "FAC"}
            return [
                ent.text.strip()
                for ent in doc.ents
                if ent.label_ in target_labels and len(ent.text.strip()) >= self.min_entity_len
            ]
        except ImportError:
            return []
        except Exception:
            return []

    def _extract_from_headings(self, text: str) -> list[str]:
        """Extract all headings as potential WikiLinks."""
        headings = re.findall(r"^#{1,4} (.+)$", text, re.MULTILINE)
        return [h.strip() for h in headings if len(h.strip()) >= self.min_entity_len]

    # ------------------------------------------------------------------
    # Body builder
    # ------------------------------------------------------------------

    def _build_body(
        self,
        result,
        title: str,
        entities: list[str],
        from_url: str = "",
        from_title: str = "",
    ) -> str:
        from .pipeline import PipelineResult
        r: PipelineResult = result

        internal_links = []
        external_links = []
        if r.extract:
            internal_links = [lnk for lnk in r.extract.links.internal[:30] if lnk.get("text")]
            external_links = [lnk for lnk in r.extract.links.external[:20] if lnk.get("text")]

        return self._build_body_raw(
            clean_markdown=r.clean_markdown,
            title=title,
            entities=entities,
            internal_links=[l["text"] for l in internal_links],
            url=r.url,
            extract_result=r.extract,
            summary=r.summary.summary if r.summary else None,
            external_links=external_links,
            from_url=from_url,
            from_title=from_title,
            agent_snapshot_lines=self._build_agent_snapshot_lines(r),
        )

    def _build_body_raw(
        self,
        clean_markdown: str,
        title: str,
        entities: list[str],
        internal_links: list[str],
        url: str,
        extract_result=None,
        summary: Optional[str] = None,
        external_links: list[dict] = None,
        from_url: str = "",
        from_title: str = "",
        agent_snapshot_lines: Optional[list[str]] = None,
    ) -> str:
        lines = []

        # Title
        lines.append(f"# {title}\n")

        # ── Navigation source ─────────────────────────────────────────────────────
        if from_url:
            label = f"[[{from_title}]]" if from_title else f"[{from_url}]({from_url})"
            lines.append(f"> 📍 From: {label}\n")

        # Summary if available
        if summary:
            lines.append("## 📝 Summary\n")
            lines.append(summary)
            lines.append("")

        if agent_snapshot_lines:
            lines.extend(agent_snapshot_lines)
            lines.append("")

        # ── Page layout ─────────────────────────────────────────────────────────
        if extract_result and extract_result.layout:
            layout = extract_result.layout
            lines.append("## 🏗️ Page Structure\n")

            # SPA warning
            if layout.framework != "static":
                spa_warn = "⚠️ " if layout.framework in ("react", "vue", "angular", "next.js", "nuxt") else ""
                lines.append(f"**Framework:** `{layout.framework}` {spa_warn}_Dynamic rendering — Playwright waited for networkidle_  ")
            if layout.has_shadow_dom:
                lines.append("**Shadow DOM:** Detected — shadow content has been injected into the HTML  ")
            lines.append("")

            if layout.sections:
                lines.append("| Region | Name/ID | Section heading | Links to |")
                lines.append("|--------|---------|-----------------|----------|")
                for sec in layout.sections:
                    tag_cell = f"`<{sec.tag}>`"
                    name_cell = f"`{sec.name[:30]}`" if sec.name and sec.name != sec.tag else "—"
                    heading_cell = sec.heading[:50] if sec.heading else "—"
                    if sec.links:
                        link_cells = []
                        for lnk in sec.links[:4]:
                            text = lnk["text"].replace("|", "｜")[:30]
                            href = lnk["href"]
                            if text and len(text) >= 3 and not self._is_noise(text):
                                link_cells.append(f"[[{text}]] [↗]({href})")
                            else:
                                link_cells.append(f"[{text or href}]({href})")
                        links_cell = " · ".join(link_cells)
                        if len(sec.links) > 4:
                            links_cell += f" _+{len(sec.links)-4} more_"
                    else:
                        links_cell = "—"
                    lines.append(f"| {tag_cell} | {name_cell} | {heading_cell} | {links_cell} |")
            lines.append("")

        lowcode_lines = self._build_lowcode_section_lines(extract_result)
        if lowcode_lines:
            lines.extend(lowcode_lines)
            lines.append("")

        # Interactive elements
        if extract_result and extract_result.interactives:
            iv = extract_result.interactives
            has_any = iv.nav_links or iv.buttons or iv.inputs or iv.selects or iv.forms
            if has_any:
                lines.append("## 🖱️ Interactive Elements\n")

                if iv.nav_links:
                    lines.append("**Navigation links:**")
                    lines.append("| Label | href | selector |")
                    lines.append("|-------|------|----------|")
                    for nl in iv.nav_links:
                        raw = (nl["text"] or nl["aria_label"] or "—")[:50]
                        text = f"[[{raw}]]" if len(raw) >= 3 and not self._is_noise(raw) else raw
                        text = text.replace("|", "｜")
                        href = nl["href"][:80]
                        sel = nl["selector"][:60]
                        lines.append(f"| {text} | `{href}` | `{sel}` |")
                    lines.append("")

                if iv.buttons:
                    lines.append("**Buttons:**")
                    lines.append("| Label | tag | type | id | selector |")
                    lines.append("|-------|-----|------|----|----------|")
                    for b in iv.buttons:
                        raw = (b["label"] or "—")[:50]
                        label = f"[[{raw}]]" if len(raw) >= 3 and not self._is_noise(raw) else raw
                        label = label.replace("|", "｜")
                        tag = b["tag"]
                        btype = b["type"] or "—"
                        bid = b["id"] or "—"
                        sel = b["selector"][:60]
                        disabled = " _(disabled)_" if b["disabled"] else ""
                        lines.append(f"| {label}{disabled} | `{tag}` | `{btype}` | `{bid}` | `{sel}` |")
                    lines.append("")

                if iv.inputs:
                    lines.append("**Input fields:**")
                    lines.append("| label | key/name | type | placeholder | required | state | selector |")
                    lines.append("|-------|----------|------|-------------|----------|-------|----------|")
                    for inp in iv.inputs:
                        itype = inp["type"]
                        name = inp.get("data_key") or inp["name"] or inp["id"] or "—"
                        label = (inp.get("label") or inp.get("aria_label") or "—").replace("|", "｜")[:40]
                        ph = (inp["placeholder"] or "—").replace("|", "｜")[:40]
                        req = "✓" if inp["required"] else ""
                        state = []
                        if inp.get("disabled"):
                            state.append("disabled")
                        if inp.get("readonly"):
                            state.append("readonly")
                        if inp.get("validation"):
                            state.append(inp.get("validation", "")[:40].replace("|", "｜"))
                        state_cell = ", ".join(state) or "—"
                        sel = inp["selector"][:60]
                        lines.append(f"| {label} | `{name}` | `{itype}` | {ph} | {req} | {state_cell} | `{sel}` |")
                    lines.append("")

                if iv.selects:
                    lines.append("**Dropdowns:**")
                    for sel in iv.selects:
                        name = sel["name"] or sel["id"] or sel["aria_label"] or "select"
                        opts = ", ".join(f"`{o['label']}`" for o in sel["options"][:8])
                        lines.append(f"- `{name}` `{sel['selector']}` → {opts}")
                    lines.append("")

                if iv.forms:
                    lines.append("**Forms:**")
                    for form in iv.forms:
                        fid = form["id"] or form["name"] or ""
                        action = form["action"] or "—"
                        method = form["method"]
                        sel = form["selector"]
                        fields = ", ".join(f"`{f['name']}` ({f['type']})" for f in form["fields"])
                        lines.append(f"- `{sel}` [{method}] → `{action}`")
                        if fid:
                            lines.append(f"  - id/name: `{fid}`")
                        if fields:
                            lines.append(f"  - fields: {fields}")
                    lines.append("")

        # Main content — wikify entities
        if clean_markdown:
            lines.append("## 📄 Content\n")
            wikified = self._wikify(clean_markdown, entities, title)
            lines.append(wikified)
            lines.append("")

        # Relationships section — core of graph view
        lines.append("## 🔗 Relationships\n")
        all_nodes = list(dict.fromkeys(
            [e for e in entities[:25]] +
            [l for l in internal_links[:15] if not self._is_noise(l)]
        ))
        if all_nodes:
            for node in all_nodes:
                clean_node = node.strip().replace("\n", " ")
                if clean_node and not self._is_noise(clean_node):
                    lines.append(f"- [[{clean_node}]]")
        else:
            lines.append("_(no entities extracted)_")
        lines.append("")

        # References
        if external_links:
            lines.append("## 🌐 References\n")
            for lnk in (external_links or [])[:15]:
                text = lnk.get("text", "").strip() or lnk.get("href", "")
                href = lnk.get("href", "")
                if text and href:
                    lines.append(f"- [{text}]({href})")
            lines.append("")

        # Source
        lines.append(f"---\n> 🔍 Source: [{url}]({url})")

        return "\n".join(lines)

    def _build_lowcode_section_lines(self, extract_result) -> list[str]:
        lowcode = getattr(extract_result, "lowcode", None) if extract_result else None
        if not lowcode or not (lowcode.platform or lowcode.components or lowcode.schema_components):
            return []

        lines = ["## Low-code / No-code Model\n"]
        if lowcode.platform:
            lines.append(f"**Platform:** `{lowcode.platform}`  ")
        if lowcode.indicators:
            lines.append(f"**Detected by:** {', '.join(f'`{item}`' for item in lowcode.indicators[:8])}  ")
        lines.append("")

        rendered = lowcode.components or []
        if rendered:
            lines.append("**Rendered components:**")
            lines.append("| Label | Key/name | Type | Required | State | Selector |")
            lines.append("|-------|----------|------|----------|-------|----------|")
            for component in rendered[:35]:
                label = self._table_text(component.get("label") or component.get("key") or "field", 50)
                key = self._table_text(component.get("key") or "-", 40)
                ctype = self._table_text(component.get("type") or "component", 30)
                required = "yes" if component.get("required") else ""
                state_bits = []
                if component.get("disabled"):
                    state_bits.append("disabled")
                if component.get("readonly"):
                    state_bits.append("readonly")
                if component.get("hidden"):
                    state_bits.append("hidden")
                validation = self._table_text(component.get("validation") or "", 60)
                if validation:
                    state_bits.append(validation)
                state = self._table_text(", ".join(state_bits) or "-", 70)
                selector = self._table_text(component.get("selector") or "-", 60)
                lines.append(f"| {label} | `{key}` | `{ctype}` | {required} | {state} | `{selector}` |")
            lines.append("")

        schema_components = lowcode.schema_components or []
        if schema_components:
            lines.append("**Embedded schema components:**")
            lines.append("| Label | Key | Type | Required |")
            lines.append("|-------|-----|------|----------|")
            for component in schema_components[:25]:
                label = self._table_text(component.get("label") or component.get("key") or "field", 50)
                key = self._table_text(component.get("key") or "-", 40)
                ctype = self._table_text(component.get("type") or "component", 30)
                required = "yes" if component.get("required") else ""
                lines.append(f"| {label} | `{key}` | `{ctype}` | {required} |")
            lines.append("")

        if lowcode.forms:
            lines.append("**Forms:**")
            for form in lowcode.forms[:8]:
                name = form.get("name") or form.get("id") or form.get("selector") or "rendered form"
                method = form.get("method") or ""
                action = form.get("action") or "current page"
                field_count = len(form.get("fields") or [])
                lines.append(f"- `{self._table_text(name, 80)}` {method} -> `{self._table_text(action, 100)}` ({field_count} fields)")

        return lines

    def _table_text(self, value, limit: int = 80) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = text.replace("|", "/").replace("\n", " ")
        return text[:limit]

    def _build_agent_snapshot_lines(self, result) -> list[str]:
        """Build a short, high-signal snapshot so an agent can orient quickly."""
        domain = urlparse(result.url).netloc.replace("www.", "")
        page_type = self._detect_page_type(result, domain)
        actions = self._detect_agent_actions(result, domain)
        framework = "static"
        section_names: list[str] = []
        nav_links = self._collect_nav_links(result, domain)

        if result.extract and result.extract.layout:
            framework = result.extract.layout.framework or "static"
            section_names = [sec.tag for sec in result.extract.layout.sections[:8]]

        lines = ["## Agent Snapshot\n"]
        lines.append(f"- **Page type:** `{page_type}`")
        lines.append(f"- **Framework:** `{framework}`")
        if section_names:
            lines.append(f"- **Layout regions:** {', '.join(section_names)}")
        if actions:
            lines.append(f"- **Likely actions:** {', '.join(f'`{action}`' for action in actions)}")

        lowcode = getattr(result.extract, "lowcode", None) if result.extract else None
        if lowcode and lowcode.platform:
            component_count = len(lowcode.components or []) + len(lowcode.schema_components or [])
            lines.append(f"- **Low-code platform:** `{lowcode.platform}` ({component_count} components)")

        content_outline = self._extract_content_outline(result.clean_markdown)
        if content_outline:
            lines.append(f"- **Main headings:** {' | '.join(content_outline[:5])}")

        if result.extract and result.extract.iframes:
            embed_types = sorted({frame.get('type', 'other') for frame in result.extract.iframes})
            lines.append(f"- **Embeds:** {', '.join(embed_types)}")

        if nav_links:
            lines.extend(["", "**Priority links:**"])
            for link in nav_links[:8]:
                title = (link.get("title") or link.get("url") or "link").replace("|", "｜")
                lines.append(f"- {title}: {link['url']}")

        if result.extract and result.extract.interactives:
            controls = self._summarize_interactives(result.extract.interactives)
            if controls:
                lines.extend(["", "**Key controls:**"])
                for control in controls:
                    lines.append(f"- {control}")

        return lines

    def _extract_content_outline(self, text: str) -> list[str]:
        headings = []
        seen = set()
        for heading in re.findall(r"^#{1,4} (.+)$", text or "", re.MULTILINE):
            clean = heading.strip()
            if clean and clean not in seen:
                seen.add(clean)
                headings.append(clean)
        return headings

    def _extract_content_excerpt(self, text: str, max_chars: int = 2200) -> str:
        if not text:
            return ""

        lines = []
        total = 0
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.lower() in {"menu", "navigation", "footer"}:
                continue
            if total and total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1

        excerpt = "\n".join(lines).strip()
        if excerpt and len(excerpt) < len(text.strip()):
            excerpt += "\n\n_(truncated)_"
        return excerpt

    def _summarize_interactives(self, interactives) -> list[str]:
        controls: list[str] = []

        for nav in interactives.nav_links[:4]:
            label = (nav.get("text") or nav.get("aria_label") or nav.get("href") or "navigation link").strip()
            selector = nav.get("selector") or ""
            controls.append(f"nav link `{label[:60]}` via `{selector[:60]}`")

        for button in interactives.buttons[:4]:
            label = (button.get("label") or button.get("aria_label") or button.get("id") or "button").strip()
            selector = button.get("selector") or ""
            controls.append(f"button `{label[:60]}` via `{selector[:60]}`")

        for input_field in interactives.inputs[:4]:
            label = (
                input_field.get("label")
                or input_field.get("data_key")
                or input_field.get("placeholder")
                or input_field.get("aria_label")
                or input_field.get("name")
                or input_field.get("id")
                or input_field.get("type")
                or "input"
            ).strip()
            selector = input_field.get("selector") or ""
            controls.append(f"input `{label[:60]}` via `{selector[:60]}`")

        for form in interactives.forms[:2]:
            action = form.get("action") or "current page"
            selector = form.get("selector") or ""
            method = form.get("method") or "GET"
            controls.append(f"form `{method}` to `{action[:80]}` via `{selector[:60]}`")

        return controls[:8]

    # ------------------------------------------------------------------
    # Wikify — replace entities in text with [[WikiLink]]
    # ------------------------------------------------------------------

    def _wikify(self, text: str, entities: list[str], page_title: str) -> str:
        """Replace entity occurrences in text with [[entity]].

        Protected zones (not wikified):
        - markdown links: [text](url "title")
        - existing [[wikilinks]]
        - URL fragments: #anchor
        - code blocks: `...` or ```...```
        """
        if not entities:
            return text

        # ── Step 1: Identify protected zones (not to be wikified) ───────────────────
        protected: list[tuple[int, int]] = []

        # Fenced code blocks ```...```
        for m in re.finditer(r"```[\s\S]*?```", text):
            protected.append((m.start(), m.end()))

        # Inline code `...`
        for m in re.finditer(r"`[^`\n]+`", text):
            protected.append((m.start(), m.end()))

        # Existing [[wikilinks]]
        for m in re.finditer(r"\[\[[^\]]*\]\]", text):
            protected.append((m.start(), m.end()))

        # Markdown links [text](url) or [text](url "title")
        for m in re.finditer(r"\[([^\]]*)\]\([^)]*\)", text):
            # Protect the entire link including optional title in parentheses
            protected.append((m.start(), m.end()))

        # Markdown link tooltips "..." inside link
        for m in re.finditer(r'\[[^\]]*\]\([^)"]*"[^"]*"\)', text):
            protected.append((m.start(), m.end()))

        # Plain URLs (http/https)
        for m in re.finditer(r"https?://\S+", text):
            protected.append((m.start(), m.end()))

        # ── Step 2: Wikify each entity once ─────────────────────────────────────────────
        sorted_ents = sorted(set(entities), key=len, reverse=True)
        already_linked: set[str] = set()

        for ent in sorted_ents:
            ent_lower = ent.lower()
            if ent_lower == page_title.lower() or ent in already_linked:
                continue
            if len(ent) < self.min_entity_len or self._is_noise(ent):
                continue

            escaped = re.escape(ent)
            pattern = re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)

            # Find first occurrence OUTSIDE protected zones
            for m in pattern.finditer(text):
                start, end = m.start(), m.end()
                if any(ps <= start < pe or ps < end <= pe for ps, pe in protected):
                    continue  # Skip if inside a protected zone

                # Replace first valid occurrence
                replacement = f"[[{ent}]]"
                text = text[:start] + replacement + text[end:]

                # Update protected ranges since text has changed
                delta = len(replacement) - (end - start)
                protected = [
                    (ps + delta if ps >= start else ps, pe + delta if pe >= start else pe)
                    for ps, pe in protected
                ]
                # Add new WikiLink to protected zone
                protected.append((start, start + len(replacement)))

                already_linked.add(ent)
                break  # Only replace the first occurrence

        return text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_title(self, result) -> str:
        if result.extract and result.extract.metadata:
            m = result.extract.metadata
            t = m.title or m.og_title
            if t:
                # Strip " - YouTube", " | GitHub" etc. suffixes
                t = re.sub(r"\s*[|\-–—]\s*(YouTube|GitHub|Wikipedia|Twitter|Reddit|Medium).*$", "", t)
                return t.strip()
        return urlparse(result.url).netloc

    def _build_tags(
        self,
        domain: str,
        result=None,
        *,
        url: str = "",
        title: str = "",
        clean_markdown: str = "",
        extract_result=None,
    ) -> list[str]:
        tags: list[str] = []
        self._append_tag(tags, "web-clip")

        for d, dtags in self.DOMAIN_TAGS.items():
            if d in domain:
                for tag in dtags:
                    self._append_tag(tags, tag)
                break

        page_url = url or getattr(result, "url", "")
        page_title = title or (self._extract_title(result) if result else "")
        page_markdown = clean_markdown or getattr(result, "clean_markdown", "") or ""
        extract = extract_result or getattr(result, "extract", None)
        metadata = extract.metadata if extract else None
        layout = extract.layout if extract else None
        lowcode = getattr(extract, "lowcode", None) if extract else None

        if result:
            page_type = self._detect_page_type(result, domain)
            if page_type in {"search", "form", "video"}:
                self._append_tag(tags, page_type)

        if layout:
            if layout.framework and layout.framework != "static":
                self._append_tag(tags, layout.framework)
            if layout.has_shadow_dom:
                self._append_tag(tags, "shadow-dom")

        if lowcode and lowcode.platform:
            self._append_tag(tags, "low-code")
            self._append_tag(tags, lowcode.platform)
            if lowcode.components or lowcode.schema_components:
                self._append_tag(tags, "form")

        if metadata:
            if metadata.og_type and metadata.og_type.lower() not in {"website", "object", "profile"}:
                self._append_tag(tags, metadata.og_type)
            for keyword in metadata.keywords[:6]:
                self._append_tag(tags, keyword)

        for tag in self._extract_url_tags(page_url, domain):
            self._append_tag(tags, tag)

        for tag in self._extract_hint_tags(page_title, metadata.description if metadata else "", page_markdown):
            self._append_tag(tags, tag)

        return tags[: self.MAX_AUTO_TAGS]

    def _append_tag(self, tags: list[str], raw_tag: str) -> None:
        tag = self._normalize_tag(raw_tag)
        if tag and tag not in tags:
            tags.append(tag)

    def _normalize_tag(self, raw_tag: str) -> str:
        if not raw_tag:
            return ""

        tag = unquote(str(raw_tag)).strip().lower()
        tag = tag.replace("&", " and ")
        tag = re.sub(r"[^\w\s-]", " ", tag, flags=re.UNICODE)
        tag = re.sub(r"[_\s]+", "-", tag)
        tag = re.sub(r"-+", "-", tag).strip("-")

        if not tag or tag in self.TAG_BLACKLIST:
            return ""
        if len(tag) < 3 or len(tag) > 40:
            return ""
        if re.fullmatch(r"\d+", tag):
            return ""
        return tag

    def _extract_url_tags(self, url: str, domain: str) -> list[str]:
        if not url:
            return []

        parsed = urlparse(url)
        raw_segments = [seg for seg in parsed.path.split("/") if seg]
        tags: list[str] = []

        if "github.com" in domain:
            if len(raw_segments) >= 2:
                self._append_tag(tags, "repository")
                self._append_tag(tags, raw_segments[1])
            if "blob" in raw_segments:
                self._append_tag(tags, "file")
                if raw_segments[-1] != "blob":
                    self._append_tag(tags, raw_segments[-1])
            if "tree" in raw_segments:
                self._append_tag(tags, "directory")
            if "issues" in raw_segments:
                self._append_tag(tags, "issues")
            if "pull" in raw_segments or "pulls" in raw_segments:
                self._append_tag(tags, "pull-request")
            if "wiki" in raw_segments:
                self._append_tag(tags, "wiki")
            segments = raw_segments[1:]
        else:
            segments = raw_segments

        for segment in segments:
            tag = self._normalize_tag(segment)
            if not tag or tag in self.TAG_BLACKLIST:
                continue
            if tag not in tags:
                tags.append(tag)
            if len(tags) >= 4:
                break

        return tags

    def _extract_hint_tags(self, title: str, description: str, clean_markdown: str) -> list[str]:
        sources = [title or "", (description or "")[:300], " ".join(self._extract_content_outline(clean_markdown)[:4])]
        combined = " ".join(part.lower() for part in sources if part).strip()
        tags: list[str] = []

        for tag, hints in self.CONTENT_TAG_HINTS.items():
            if any(hint in combined for hint in hints):
                tags.append(tag)

        title_tag = self._normalize_tag(title)
        if title_tag and title_tag.count("-") <= 3:
            tags.append(title_tag)

        return tags

    def _is_noise(self, text: str) -> bool:
        text = text.strip()
        if text.lower() in self.NAV_BLACKLIST:
            return True
        for pattern in self.NOISE_PATTERNS:
            if re.match(pattern, text, re.IGNORECASE):
                return True
        return len(text) < self.min_entity_len

    # ------------------------------------------------------------------
    # Multi-file vault output (agent-readable knowledge graph)
    # ------------------------------------------------------------------

    def format_multi(
        self,
        pipeline_result,
        note_title: Optional[str] = None,
        from_url: str = "",
        from_title: str = "",
    ) -> list[tuple[str, "ObsidianNote"]]:
        """
        Create multiple Obsidian files from one URL to build a knowledge graph.

        Returns: [(relative_path, ObsidianNote), ...]
          - "[Title].md"              main note with nav table + agent frontmatter + layout
          - "_map/[domain].md"        full link map for the domain
          - "_entities/[Name].md"     stub for each entity (creates graph edges)

        from_url / from_title: page that led to this URL (for backlink creation).
        Agent reads vault → sees WikiLinks → knows which URLs to navigate next.
        """
        files: list[tuple[str, ObsidianNote]] = []
        result = pipeline_result
        domain = urlparse(result.url).netloc.replace("www.", "")

        # ── 1. Main note ──────────────────────────────────────────────────────
        main_note = self.format(result, note_title, from_url=from_url, from_title=from_title)
        safe_title = re.sub(r'[<>:"/\\|?*\n\r]', "", main_note.frontmatter.get("title", "note")).strip()[:120]

        # Collect nav links
        nav_links = self._collect_nav_links(result, domain)

        # Enhance frontmatter with agent-readable info
        main_note.frontmatter["page_type"] = self._detect_page_type(result, domain)
        main_note.frontmatter["nav_urls"] = [lnk["url"] for lnk in nav_links if lnk["type"] == "internal"][:25]
        main_note.frontmatter["agent_actions"] = self._detect_agent_actions(result, domain)
        if from_url:
            main_note.frontmatter["from_url"] = from_url
        if result.extract and result.extract.layout:
            lay = result.extract.layout
            main_note.frontmatter["framework"] = lay.framework
            if lay.has_shadow_dom:
                main_note.frontmatter["has_shadow_dom"] = True
            main_note.frontmatter["layout_sections"] = [
                s.tag for s in lay.sections
            ]

        # Inject navigation section at end of body
        nav_section = self._build_nav_section(nav_links)
        enhanced_note = ObsidianNote(
            frontmatter=main_note.frontmatter,
            body=main_note.body + nav_section,
        )

        files.append((f"{safe_title}.md", enhanced_note))

        # ── 2. Site map note ──────────────────────────────────────────────────
        map_note = self._build_map_note(result, domain, nav_links, safe_title)
        files.append((f"_map/{domain}.md", map_note))

        # ── 3. Entity stubs ───────────────────────────────────────────────────
        entities = main_note.frontmatter.get("entities", [])
        for entity in entities[:20]:
            if self._is_noise(entity) or len(entity) < self.min_entity_len:
                continue
            safe_ent = re.sub(r'[<>:"/\\|?*\n\r]', "", entity).strip()[:80]
            if not safe_ent:
                continue
            stub = self._build_entity_stub(entity, safe_title, result.url)
            files.append((f"_entities/{safe_ent}.md", stub))

        return files

    def _collect_nav_links(
        self,
        result,
        domain: str,
        max_internal: int = 60,
        max_external: int = 25,
    ) -> list[dict]:
        """Collect all navigation-worthy links from the page."""
        internal_links: list[dict] = []
        external_links: list[dict] = []
        seen_urls: set[str] = set()

        if not result.extract:
            return []

        for lnk in result.extract.links.internal:
            text = (lnk.get("text") or "").strip()
            href = self._normalize_nav_url((lnk.get("href") or "").strip())
            if not text or not href or href in seen_urls or self._is_noise(text):
                continue
            seen_urls.add(href)
            safe = re.sub(r'[<>:"/\\|?*\n\r]', "", text)[:60].strip()
            internal_links.append({
                "title": text[:80],
                "note": f"[[{safe}]]" if safe else "",
                "url": href,
                "type": "internal",
            })
            if len(internal_links) >= max_internal:
                break

        for lnk in result.extract.links.external:
            text = (lnk.get("text") or "").strip()
            href = self._normalize_nav_url((lnk.get("href") or "").strip())
            if not text or not href or href in seen_urls or self._is_noise(text):
                continue
            seen_urls.add(href)
            external_links.append({
                "title": text[:80],
                "note": "",
                "url": href,
                "type": "external",
            })
            if len(external_links) >= max_external:
                break

        internal_links.sort(key=self._sort_nav_link_key)
        external_links.sort(key=self._sort_nav_link_key)
        return internal_links + external_links

    def _build_nav_section(self, nav_links: list[dict]) -> str:
        """Build ## Navigation section so the agent knows which links to follow."""
        if not nav_links:
            return ""

        internal = [l for l in nav_links if l["type"] == "internal"]
        external = [l for l in nav_links if l["type"] == "external"]
        lines = ["\n\n## 🗺️ Navigation\n"]

        if internal:
            lines.append("### 📍 Internal pages\n")
            lines.append("| Page | URL |")
            lines.append("|------|-----|")
            for lnk in internal[:30]:
                display = lnk["note"] if lnk["note"] else lnk["title"].replace("|", "｜")
                url = lnk["url"]
                lines.append(f"| {display} | {url} |")

        if external:
            lines.append("\n### 🌐 External links\n")
            lines.append("| Page | URL |")
            lines.append("|------|-----|")
            for lnk in external[:20]:
                title = lnk["title"].replace("|", "｜")
                url = lnk["url"]
                lines.append(f"| [{title}]({url}) | {url} |")

        return "\n".join(lines)

    def _detect_page_type(self, result, domain: str) -> str:
        """Classify page type so the agent understands the context."""
        url = result.url.lower()
        if "youtube.com" in domain or "youtu.be" in domain:
            return "video"
        if any(x in url for x in ["/search", "?q=", "?s=", "?query=", "?search="]):
            return "search"
        if any(x in url for x in ["/login", "/signin", "/register", "/signup"]):
            return "form"
        if result.extract:
            lowcode = getattr(result.extract, "lowcode", None)
            if lowcode and (lowcode.components or lowcode.schema_components or lowcode.forms):
                return "form"
            if result.extract.interactives and (result.extract.interactives.forms or len(result.extract.interactives.inputs) >= 2):
                return "form"
            if len(result.extract.links.internal) > 30:
                return "listing"
        if not result.clean_markdown or len(result.clean_markdown) < 200:
            return "stub"
        return "article"

    def _detect_agent_actions(self, result, domain: str) -> list[str]:
        """List actions the agent can perform on this page."""
        actions = ["read_content"]
        if result.extract:
            lowcode = getattr(result.extract, "lowcode", None)
            if lowcode and (lowcode.components or lowcode.schema_components):
                actions.append("inspect_form_schema")
                actions.append("fill_form")
            if result.extract.links.internal:
                actions.append("follow_internal_links")
            if result.extract.links.external:
                actions.append("visit_external_links")
            if result.extract.iframes:
                types = {f["type"] for f in result.extract.iframes}
                if "youtube" in types:
                    actions.append("watch_embedded_video")
                if "maps" in types:
                    actions.append("view_map")
                if "spotify" in types:
                    actions.append("listen_audio")
        if "youtube.com" in domain:
            actions.append("watch_video")
        return actions

    def _normalize_nav_url(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(fragment="").geturl()

    def _sort_nav_link_key(self, link: dict) -> tuple:
        parsed = urlparse(link.get("url", ""))
        segments = [seg for seg in parsed.path.split("/") if seg]
        return (
            len(segments),
            parsed.path.lower(),
            parsed.query.lower(),
            (link.get("title") or "").lower(),
        )

    def _build_map_note(
        self,
        result,
        domain: str,
        nav_links: list[dict],
        source_title: str,
        site_map_config: Optional[SiteMapConfig] = None,
    ) -> "ObsidianNote":
        """Create a navigation map note for the full domain."""
        today = self._today()
        config = site_map_config or SiteMapConfig()
        internal = [l for l in nav_links if l["type"] == "internal"][:config.max_internal_links]
        external = [l for l in nav_links if l["type"] == "external"][:config.max_external_links]
        map_title = f"{source_title} - Site Map"

        body_lines = [
            f"# 🗺️ Site Map — {source_title}\n",
            f"_Updated: {today} | Source: [[{source_title}]]_\n",
            "## Overview\n",
            f"- **Domain:** `{domain}`",
            f"- **Root URL:** https://{domain}",
            f"- **Map style:** `{config.style}`",
            f"- **Tree depth:** `{config.max_depth}`",
            f"- **Internal links captured:** {len(internal)}",
            f"- **External links captured:** {len(external)}",
            "",
        ]

        if internal:
            if config.style in {"tree", "both"}:
                body_lines.append("## 🌲 URL Tree\n")
                body_lines.extend(self._build_internal_tree_lines(internal, config.max_depth))
                body_lines.append("")

            if config.style in {"table", "both"}:
                body_lines.append("## 📋 Internal pages\n")
                body_lines.append("| Page | URL |")
                body_lines.append("|------|-----|")
                for lnk in internal:
                    note = lnk["note"] if lnk["note"] else lnk["title"].replace("|", "｜")
                    body_lines.append(f"| {note} | {lnk['url']} |")
        else:
            body_lines.append("## 📋 Internal pages\n")
            body_lines.append("_(no internal pages found)_")

        if external:
            body_lines.append("\n## 🌐 External links\n")
            body_lines.append("| Page | URL |")
            body_lines.append("|------|-----|")
            for lnk in external:
                title = lnk["title"].replace("|", "｜")
                body_lines.append(f"| [{title}]({lnk['url']}) | {lnk['url']} |")

        body_lines.append(f"\n---\n> Auto-generated by Browser-Analyse from: {result.url}")

        frontmatter = {
            "title": map_title,
            "domain": domain,
            "map_for": domain,
            "last_updated": today,
            "source_page": result.url,
            "map_style": config.style,
            "tree_depth": config.max_depth,
            "internal_links_count": len(internal),
            "external_links_count": len(external),
            "tags": ["site-map", "tree-map", "navigation", "agent-index"],
        }

        return ObsidianNote(frontmatter=frontmatter, body="\n".join(body_lines))

    def _build_internal_tree_lines(self, internal_links: list[dict], max_depth: int) -> list[str]:
        tree = {"children": {}, "links": []}

        for link in internal_links:
            parsed = urlparse(link["url"])
            segments = [
                self._format_path_segment(seg)
                for seg in parsed.path.split("/")
                if seg
            ]

            node = tree
            for segment in segments[:max_depth]:
                key = segment.lower()
                if key not in node["children"]:
                    node["children"][key] = {
                        "label": segment,
                        "children": {},
                        "links": [],
                    }
                node = node["children"][key]

            node["links"].append(link)

        lines = ["- `/`"]
        lines.extend(self._render_tree_branch(tree, depth=1))
        return lines

    def _render_tree_branch(self, node: dict, depth: int) -> list[str]:
        indent = "  " * depth
        lines: list[str] = []

        for child in sorted(node["children"].values(), key=lambda item: item["label"].lower()):
            lines.append(f"{indent}- `{child['label']}/`")
            lines.extend(self._render_tree_branch(child, depth + 1))

        for link in sorted(node["links"], key=self._sort_nav_link_key):
            display = link["note"] if link["note"] else link["title"].replace("|", "｜")
            lines.append(f"{indent}- {display} → {link['url']}")

        return lines

    def _format_path_segment(self, segment: str) -> str:
        label = unquote(segment).strip()
        label = re.sub(r"[-_]+", " ", label)
        label = re.sub(r"\s+", " ", label)
        return label[:40] or "root"

    def _build_entity_stub(
        self,
        entity: str,
        seen_in_title: str,
        url: str,
    ) -> "ObsidianNote":
        """Create a stub note for an entity — creates a graph node in Obsidian."""
        body = (
            f"# {entity}\n\n"
            f"_Entity extracted from [[{seen_in_title}]]_\n\n"
            f"> 🔍 Source: [{url}]({url})\n"
        )
        frontmatter = {
            "type": "entity",
            "seen_in": [f"[[{seen_in_title}]]"],
            "source_url": url,
            "tags": ["entity"],
        }
        return ObsidianNote(frontmatter=frontmatter, body=body)

    # ------------------------------------------------------------------
    # Section-split output — one sub-note per page region
    # ------------------------------------------------------------------

    # Maps LayoutSection.tag → human-readable file base name
    _SECTION_TAG_NAMES: dict = {
        "header": "Header",
        "nav": "Navigation",
        "main": "Main",
        "article": "Article",
        "aside": "Aside",
        "footer": "Footer",
        "section": "Section",
        "div.header": "Header",
        "div.nav": "Navigation",
        "div.main": "Main",
        "div.aside": "Aside",
        "div.footer": "Footer",
    }

    def format_split(
        self,
        pipeline_result,
        note_title: Optional[str] = None,
        from_url: str = "",
        from_title: str = "",
        site_map_config: Optional[SiteMapConfig] = None,
    ) -> list:
        """
        Split a page into multiple sub-notes by layout section.

        Returns a list of (filename, markdown_content) pairs intended to be
        saved into vault/{Title}/ subfolder.

        Naming convention (unique across entire vault):
          - {Title}.md                        — index / overview note
          - {Title} - {Section}.md            — one file per LayoutSection
          - {Title} - Interactive Elements.md — buttons / inputs / forms (if present)

        This allows cross-page WikiLinks like [[GitHub Explore - Navigation]]
        to resolve correctly even when multiple sites are in the same vault.
        """
        result = pipeline_result
        domain = urlparse(result.url).netloc.replace("www.", "")
        title = note_title or self._extract_title(result)
        # Sanitised title used in all filenames and wikilinks
        safe_title = re.sub(r'[<>:"/\\|?*\n\r]', "", title).strip()[:80] or "Untitled"
        tags = self._build_tags(domain, result)
        entities = self._extract_entities(result.clean_markdown, result)
        today = datetime.now().strftime("%Y-%m-%d")

        sections = []
        if result.extract and result.extract.layout:
            sections = result.extract.layout.sections or []

        # ── Assign section short-names (used as the {Section} part) ──────
        name_counts: dict = {}
        section_files: list = []  # (section_short_name, LayoutSection)
        for sec in sections:
            base = self._SECTION_TAG_NAMES.get(sec.tag, sec.tag.replace(".", "-").title())
            if sec.heading and sec.heading != base:
                safe_heading = re.sub(r'[<>:"/\\|?*\n\r]', "", sec.heading).strip()[:40]
                if safe_heading and safe_heading.lower() != base.lower():
                    base = safe_heading
            count = name_counts.get(base, 0) + 1
            name_counts[base] = count
            short = base if count == 1 else f"{base} {count}"
            section_files.append((short, sec))

        # Build full file-stem per section: "{safe_title} - {short}"
        def sec_stem(short: str) -> str:
            return f"{safe_title} - {short}"

        ie_stem = f"{safe_title} - Interactive Elements"
        site_map_stem = f"{safe_title} - Site Map"

        # Which section receives the clean_markdown content
        content_section = next(
            (short for short, s in section_files if s.tag in ("main", "article")),
            section_files[0][0] if section_files else None,
        )

        output: list = []

        # ── 1. {Title}.md  (index / overview) ────────────────────────────
        fm_parts = [
            "---",
            f"title: {safe_title}",
            f'url: "{result.url}"',
            f"domain: {domain}",
            f"fetched: {today}",
            "tags:",
        ]
        for t in tags:
            fm_parts.append(f"  - {t}")
        if entities:
            fm_parts.append("entities:")
            for e in sorted(entities)[:30]:
                e_safe = str(e).replace('"', '\\"')
                fm_parts.append(f'  - "{e_safe}"')
        if result.extract and result.extract.layout:
            lay = result.extract.layout
            fm_parts.append(f"framework: {lay.framework}")
            fm_parts.append(f"has_shadow_dom: {str(lay.has_shadow_dom).lower()}")
        if result.extract and getattr(result.extract, "lowcode", None) and result.extract.lowcode.platform:
            fm_parts.append(f"lowcode_platform: {result.extract.lowcode.platform}")
            fm_parts.append(f"lowcode_components_count: {len(result.extract.lowcode.components)}")
        fm_parts.append("---")
        frontmatter_str = "\n".join(fm_parts)

        index_lines = [frontmatter_str, "", f"# {title}\n"]
        if from_url:
            label = f"[[{from_title}]]" if from_title else f"[{from_url}]({from_url})"
            index_lines.append(f"> 📍 From: {label}\n")

        # Framework info
        if result.extract and result.extract.layout:
            lay = result.extract.layout
            if lay.framework != "static":
                index_lines.append(f"**Framework:** `{lay.framework}`  ")
            if lay.has_shadow_dom:
                index_lines.append("**Shadow DOM:** detected  ")
            if result.extract and getattr(result.extract, "lowcode", None) and result.extract.lowcode.platform:
                index_lines.append(f"**Low-code platform:** `{result.extract.lowcode.platform}`  ")
            index_lines.append("")

        # Sub-pages list — wikilinks use full unique stems
        if section_files:
            index_lines.append("## 📑 Sub-pages\n")
            for short, sec in section_files:
                heading_hint = f" — {sec.heading}" if sec.heading else ""
                index_lines.append(f"- [[{sec_stem(short)}|{short}]] `<{sec.tag}>`{heading_hint}")
            iv = result.extract.interactives if result.extract else None
            if iv and (iv.buttons or iv.inputs or iv.forms or iv.nav_links):
                index_lines.append(f"- [[{ie_stem}|Interactive Elements]]")
            if site_map_config:
                index_lines.append(f"- [[{site_map_stem}|Site Map]]")
            index_lines.append("")

        # Structure table
        if sections:
            index_lines.append("## 🏗️ Page Structure\n")
            index_lines.append("| Region | Sub-note | Heading |")
            index_lines.append("|--------|----------|---------|")
            for short, sec in section_files:
                heading_cell = sec.heading[:60] if sec.heading else "—"
                index_lines.append(f"| `<{sec.tag}>` | [[{sec_stem(short)}\\|{short}]] | {heading_cell} |")
            index_lines.append("")

        lowcode_lines = self._build_lowcode_section_lines(result.extract if result.extract else None)
        if lowcode_lines:
            index_lines.extend(lowcode_lines)
            index_lines.append("")

        # Relationships
        index_lines.append("## 🔗 Relationships\n")
        internal_texts = []
        if result.extract:
            internal_texts = [
                lnk["text"] for lnk in result.extract.links.internal[:30]
                if lnk.get("text") and not self._is_noise(lnk["text"])
            ]
        all_nodes = list(dict.fromkeys([e for e in entities[:25]] + internal_texts[:15]))
        if all_nodes:
            for node in all_nodes:
                clean_node = node.strip().replace("\n", " ")
                if clean_node and not self._is_noise(clean_node):
                    index_lines.append(f"- [[{clean_node}]]")
        else:
            index_lines.append("_(no entities extracted)_")
        index_lines.append("")

        # References
        if result.extract and result.extract.links.external:
            index_lines.append("## 🌐 References\n")
            for lnk in result.extract.links.external[:15]:
                text = (lnk.get("text") or "").strip() or lnk.get("href", "")
                href = lnk.get("href", "")
                if text and href:
                    index_lines.append(f"- [{text}]({href})")
            index_lines.append("")

        index_lines.append(f"---\n> 🔍 Source: [{result.url}]({result.url})")
        output.append((f"{safe_title}.md", "\n".join(index_lines)))

        # ── 2. Section sub-notes ──────────────────────────────────────────
        for short, sec in section_files:
            stem = sec_stem(short)
            sec_fm_lines = [
                "---",
                f"title: {stem}",
                f'parent: "[[{safe_title}]]"',
                f"section_tag: {sec.tag}",
                f'page: "{result.url}"',
                "tags:",
                "  - web-section",
                "---",
            ]
            sec_lines = ["\n".join(sec_fm_lines), "", f"# {short}\n"]

            meta_parts = [f"**Tag:** `<{sec.tag}>`"]
            if sec.name and sec.name != sec.tag:
                meta_parts.append(f"**Region:** `{sec.name[:40]}`")
            if sec.role:
                meta_parts.append(f"**Role:** `{sec.role}`")
            sec_lines.append(" · ".join(meta_parts) + "  \n")

            if sec.heading:
                sec_lines.append(f"> {sec.heading}\n")

            if sec.text_preview:
                sec_lines.append(f"_{sec.text_preview[:200]}_\n")

            if sec.links:
                sec_lines.append("**Links in this region:**\n")
                sec_lines.append("| Text | URL |")
                sec_lines.append("|------|-----|")
                for lnk in sec.links:
                    text = (lnk.get("text") or "").replace("|", "｜")[:60]
                    href = lnk.get("href", "")
                    display = f"[[{text}]]" if text and len(text) >= 3 and not self._is_noise(text) else (text or href)
                    sec_lines.append(f"| {display} | {href} |")
                sec_lines.append("")

            # Full clean_markdown goes to the main/article section
            if short == content_section and result.clean_markdown:
                sec_lines.append("## 📄 Content\n")
                wikified = self._wikify(result.clean_markdown, entities, title)
                sec_lines.append(wikified)
                sec_lines.append("")

            sec_lines.append(f"---\n> ↩ [[{safe_title}]] · 🔍 [{result.url}]({result.url})")
            output.append((f"{stem}.md", "\n".join(sec_lines)))

        # ── 3. Interactive Elements sub-note ──────────────────────────────
        if result.extract and result.extract.interactives:
            iv = result.extract.interactives
            has_any = iv.nav_links or iv.buttons or iv.inputs or iv.selects or iv.forms
            if has_any:
                ie_fm = "\n".join([
                    "---",
                    f"title: {ie_stem}",
                    f'parent: "[[{safe_title}]]"',
                    f'page: "{result.url}"',
                    "tags:",
                    "  - web-section",
                    "  - interactive",
                    "---",
                ])
                ie_lines = [ie_fm, "", "# Interactive Elements\n",
                            f"> Scraped from [[{safe_title}]] · [{result.url}]({result.url})\n"]

                if iv.nav_links:
                    ie_lines.append("## Navigation Links\n")
                    ie_lines.append("| Label | href | selector |")
                    ie_lines.append("|-------|------|----------|")
                    for nl in iv.nav_links:
                        raw = (nl["text"] or nl.get("aria_label") or "—")[:50]
                        text = f"[[{raw}]]" if len(raw) >= 3 and not self._is_noise(raw) else raw
                        text = text.replace("|", "｜")
                        ie_lines.append(f"| {text} | `{nl['href'][:80]}` | `{nl['selector'][:60]}` |")
                    ie_lines.append("")

                if iv.buttons:
                    ie_lines.append("## Buttons\n")
                    ie_lines.append("| Label | tag | type | id | selector |")
                    ie_lines.append("|-------|-----|------|----|----------|")
                    for b in iv.buttons:
                        raw = (b["label"] or "—")[:50]
                        label = f"[[{raw}]]" if len(raw) >= 3 and not self._is_noise(raw) else raw
                        label = label.replace("|", "｜")
                        disabled = " _(disabled)_" if b["disabled"] else ""
                        ie_lines.append(f"| {label}{disabled} | `{b['tag']}` | `{b['type'] or '—'}` | `{b['id'] or '—'}` | `{b['selector'][:60]}` |")
                    ie_lines.append("")

                if iv.inputs:
                    ie_lines.append("## Input Fields\n")
                    ie_lines.append("| type | name / id | placeholder | required | selector |")
                    ie_lines.append("|------|-----------|-------------|----------|----------|")
                    for inp in iv.inputs:
                        name = inp["name"] or inp["id"] or "—"
                        ph = (inp["placeholder"] or "—").replace("|", "｜")[:40]
                        req = "✓" if inp["required"] else ""
                        ie_lines.append(f"| `{inp['type']}` | `{name}` | {ph} | {req} | `{inp['selector'][:60]}` |")
                    ie_lines.append("")

                if iv.selects:
                    ie_lines.append("## Dropdowns\n")
                    for sel in iv.selects:
                        name = sel["name"] or sel["id"] or sel.get("aria_label") or "select"
                        opts = ", ".join(f"`{o['label']}`" for o in sel["options"][:8])
                        ie_lines.append(f"- `{name}` → {opts}")
                        ie_lines.append(f"  - selector: `{sel['selector']}`")
                    ie_lines.append("")

                if iv.forms:
                    ie_lines.append("## Forms\n")
                    for form in iv.forms:
                        fid = form["id"] or form["name"] or "—"
                        action = form["action"] or "—"
                        fields = ", ".join(f"`{f['name']}` ({f['type']})" for f in form["fields"])
                        ie_lines.append(f"- **`{fid}`** [{form['method']}] → `{action}`")
                        ie_lines.append(f"  - fields: {fields}")
                        ie_lines.append(f"  - selector: `{form['selector']}`")
                    ie_lines.append("")

                ie_lines.append(f"---\n> ↩ [[{safe_title}]]")
                output.append((f"{ie_stem}.md", "\n".join(ie_lines)))

        if site_map_config:
            site_map_note = self.build_site_map(
                result,
                note_title=title,
                site_map_config=site_map_config,
            )
            output.append((f"{site_map_stem}.md", site_map_note.render()))

        return output

