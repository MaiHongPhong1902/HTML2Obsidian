"""
tools/obsidian_tool.py — Tool calling module: URL → Obsidian Note.

Usage as an LLM agent tool function:
    from tools import create_obsidian_note, TOOL_SCHEMA
    result = create_obsidian_note(url="https://example.com", vault_path="./vault")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from .pipeline import BrowserPipeline
from .obsidian_formatter import ObsidianFormatter, SiteMapConfig

LLM_SECTION_HEADINGS = {
    "summary": "## 📝 Summary",
    "agent_snapshot": "## Agent Snapshot",
    "page_structure": "## 🏗️ Page Structure",
    "interactive_elements": "## 🖱️ Interactive Elements",
    "content": "## 📄 Content",
    "relationships": "## 🔗 Relationships",
    "references": "## 🌐 References",
    "navigation": "## 🗺️ Navigation",
}

PROTECTED_FRONTMATTER_FIELDS = {
    "title",
    "url",
    "domain",
    "fetched",
    "tags",
    "entities",
    "from_url",
    "framework",
    "has_shadow_dom",
    "video_id",
    "channel",
    "upload_date",
    "duration",
    "map_for",
    "last_updated",
    "source_page",
    "map_style",
    "tree_depth",
    "internal_links_count",
    "external_links_count",
}

MAX_LLM_STRUCTURED_ITEMS = 20
MAX_LLM_FRONTMATTER_ITEMS = 20
MAX_LLM_TAGS = 20

# ──────────────────────────────────────────────────────────────────────────────
# Tool schema — pass directly to OpenAI / Ollama / Anthropic tool calling
# ──────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "create_obsidian_note",
    "description": (
        "Fetch a URL and create an Obsidian Markdown note with YAML frontmatter, "
        "[[WikiLinks]] for key entities, smart auto-generated tags from domain/metadata/URL signals, "
        "and Relationships / References sections. "
        "Supports SPA pages (React/Vue/Next.js), Wikipedia, YouTube, GitHub, arXiv, "
        "and can optionally generate a dedicated hierarchical site/tree map note."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL of the page to create a note from (must start with http/https).",
            },
            "vault_path": {
                "type": "string",
                "description": (
                    "Path to the Obsidian vault directory to save the .md file. "
                    "If empty, the note is returned in the 'content' field without saving."
                ),
                "default": "",
            },
            "note_title": {
                "type": "string",
                "description": "Custom note title. If empty, auto-detected from the page.",
                "default": "",
            },
            "render_js": {
                "type": "boolean",
                "description": (
                    "Render JavaScript via Playwright before extracting content. "
                    "Enable for SPA/React/Vue pages, disable for faster static page fetching."
                ),
                "default": True,
            },
            "extra_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional tags to append to the frontmatter.",
                "default": [],
            },
            "from_url": {
                "type": "string",
                "description": "Source URL for backlink creation (if this note was reached from another page).",
                "default": "",
            },
            "from_title": {
                "type": "string",
                "description": "Title of the source page (used with from_url).",
                "default": "",
            },
            "browser_profile": {
                "type": "string",
                "description": (
                    "Reuse an existing browser profile for cookies and login sessions. "
                    "Accepts a shortcut (\"chrome\", \"edge\", \"firefox\") or an absolute "
                    "path to a Chromium user-data directory."
                ),
                "default": "",
            },
            "split_sections": {
                "type": "boolean",
                "description": (
                    "Split the page into multiple sub-notes by layout section. "
                    "Saves an index.md + one .md per page region into vault/{Title}/ subfolder. "
                    "Requires vault_path to be set."
                ),
                "default": False,
            },
            "include_site_map": {
                "type": "boolean",
                "description": (
                    "Generate a dedicated site map note with a hierarchical URL tree "
                    "built from the page's internal navigation links."
                ),
                "default": False,
            },
            "site_map_style": {
                "type": "string",
                "description": (
                    "How to render the site map: 'tree' for a hierarchical URL tree, "
                    "'table' for a flat link table, or 'both' to include both views."
                ),
                "default": "tree",
            },
            "site_map_max_depth": {
                "type": "integer",
                "description": "Maximum URL path depth to expand when rendering the site map tree.",
                "default": 3,
            },
            "site_map_max_internal_links": {
                "type": "integer",
                "description": "Maximum number of internal links to include in the site map.",
                "default": 120,
            },
            "site_map_max_external_links": {
                "type": "integer",
                "description": "Maximum number of external links to include in the site map.",
                "default": 30,
            },
            "llm_config": {
                "type": "object",
                "description": (
                    "Optional LLM-safe controls. Lets the model request structured source data "
                    "and apply validated note edits while keeping tool-managed fields protected. "
                    "Any llm_config.edit change requires explicit user approval."
                ),
                "properties": {
                    "user_approved_edits": {
                        "type": "boolean",
                        "description": "Must be true before the tool will apply any llm_config.edit content changes.",
                        "default": False,
                    },
                    "include_structured_data": {
                        "type": "boolean",
                        "description": "Return structured source data so the LLM can inspect metadata, links, layout, and interactives.",
                        "default": False,
                    },
                    "structured_data_limit": {
                        "type": "integer",
                        "description": "Maximum number of items to include per structured list.",
                        "default": 10,
                    },
                    "edit": {
                        "type": "object",
                        "description": "Safe note edits validated by the tool. Requires llm_config.user_approved_edits=true.",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Optional replacement note title. Sanitized by tool rules.",
                            },
                            "add_tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Extra tags to add after auto-tag generation.",
                                "default": [],
                            },
                            "remove_tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tags to remove from the final note if present.",
                                "default": [],
                            },
                            "frontmatter_fields": {
                                "type": "object",
                                "description": "Additional frontmatter fields. Protected tool fields are rejected.",
                                "default": {},
                            },
                            "include_sections": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "summary",
                                        "agent_snapshot",
                                        "page_structure",
                                        "interactive_elements",
                                        "content",
                                        "relationships",
                                        "references",
                                        "navigation"
                                    ],
                                },
                                "description": "Only keep these top-level note sections in the rendered note.",
                                "default": [],
                            },
                            "exclude_sections": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "summary",
                                        "agent_snapshot",
                                        "page_structure",
                                        "interactive_elements",
                                        "content",
                                        "relationships",
                                        "references",
                                        "navigation"
                                    ],
                                },
                                "description": "Drop these top-level note sections from the rendered note.",
                                "default": [],
                            },
                        },
                        "default": {},
                    },
                },
                "default": {},
            },
            "capture_network": {
                "type": "boolean",
                "description": "Capture XHR/fetch network requests made during page load. Results appear in browser_context.network_requests.",
                "default": False,
            },
        },
        "required": ["url"],
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Main tool function
# ──────────────────────────────────────────────────────────────────────────────

def create_obsidian_note(
    url: str,
    vault_path: str = "",
    note_title: str = "",
    render_js: bool = True,
    extra_tags: list[str] | None = None,
    from_url: str = "",
    from_title: str = "",
    browser_profile: Optional[str] = None,
    split_sections: bool = False,
    include_site_map: bool = False,
    site_map_style: str = "tree",
    site_map_max_depth: int = 3,
    site_map_max_internal_links: int = 120,
    site_map_max_external_links: int = 30,
    llm_config: Optional[dict] = None,
    capture_network: bool = False,            # capture XHR/fetch requests in browser_context
) -> dict:
    """
    Create an Obsidian note from a URL.

    Returns:
        dict:
            success  (bool)  — whether the operation succeeded
            title    (str)   — note title
            content  (str)   — full Markdown content
            agent_context (str) — compact agent-oriented context summary
            site_map (str) — dedicated site map / tree map note content
            structured_data (dict | None) — LLM-readable structured snapshot of the page
            applied_llm_config (dict) — accepted/rejected LLM-safe edits
            browser_context (dict) — spa_framework, page_metrics, network_requests, embedded_json, json_ld
            path     (str)   — saved file path (empty if not saved)
            site_map_path (str) — saved site map path (empty if not saved)
            url      (str)   — original URL
            tags     (list)  — assigned tags
            entities (list)  — extracted entities
            error    (str)   — error description if failed
    """
    extra_tags = extra_tags or []
    llm_config = llm_config or {}

    try:
        normalized_llm = _normalize_llm_config(llm_config)
    except ValueError as exc:
        return {
            "success": False,
            "title": "",
            "content": "",
            "agent_context": "",
            "site_map": "",
            "structured_data": None,
            "applied_llm_config": {"accepted": [], "rejected": [str(exc)]},
            "browser_context": None,
            "path": "",
            "site_map_path": "",
            "url": url,
            "tags": [],
            "entities": [],
            "error": str(exc),
        }

    requested_title = normalized_llm["edit"]["title"] or note_title or None

    pipeline = BrowserPipeline(
        render_js=render_js,
        browser_profile=browser_profile,
        capture_network=capture_network,
    )
    result = pipeline.run(url)

    if result.fetch_error:
        return {
            "success": False,
            "title": "",
            "content": "",
            "agent_context": "",
            "site_map": "",
            "structured_data": None,
            "applied_llm_config": {"accepted": [], "rejected": []},
            "browser_context": result.browser_context,
            "path": "",
            "site_map_path": "",
            "url": url,
            "tags": [],
            "entities": [],
            "error": result.fetch_error,
        }

    formatter = ObsidianFormatter(use_spacy=False)
    agent_context = formatter.format_agent_context(result, note_title=requested_title)
    try:
        site_map_config = SiteMapConfig(
            style=site_map_style,
            max_internal_links=site_map_max_internal_links,
            max_external_links=site_map_max_external_links,
            max_depth=site_map_max_depth,
        ) if include_site_map else None
    except ValueError as exc:
        return {
            "success": False,
            "title": "",
            "content": "",
            "agent_context": "",
            "site_map": "",
            "structured_data": None,
            "applied_llm_config": {"accepted": [], "rejected": [str(exc)]},
            "browser_context": result.browser_context,
            "path": "",
            "site_map_path": "",
            "url": url,
            "tags": [],
            "entities": [],
            "error": str(exc),
        }

    # ── Split-sections mode ───────────────────────────────────────────────────
    if split_sections:
        files = formatter.format_split(
            result,
            note_title=requested_title,
            from_url=from_url,
            from_title=from_title,
            site_map_config=site_map_config,
        )

        # Infer title and tags from index.md frontmatter (first file)
        _first_content = files[0][1] if files else ""
        _title_match = re.search(r"^title:\s*(.+)$", _first_content, re.MULTILINE)
        title = _title_match.group(1).strip() if _title_match else (requested_title or "Untitled")
        _tags_match = re.findall(r"^  - (.+)$", _first_content, re.MULTILINE)
        tags = _tags_match[:10]
        llm_state = {
            "accepted": [],
            "rejected": list(normalized_llm.get("rejected", [])),
            "protected_frontmatter_fields": sorted(PROTECTED_FRONTMATTER_FIELDS),
            "editable_sections": list(LLM_SECTION_HEADINGS.keys()),
        }
        if normalized_llm["include_structured_data"]:
            llm_state["accepted"].append("include_structured_data")
        if normalized_llm["edit"].get("title"):
            llm_state["accepted"].append("edit.title")
        unsupported_split_edits = any([
            normalized_llm["edit"].get("add_tags"),
            normalized_llm["edit"].get("remove_tags"),
            normalized_llm["edit"].get("frontmatter_fields"),
            normalized_llm["edit"].get("include_sections"),
            normalized_llm["edit"].get("exclude_sections"),
        ])
        if unsupported_split_edits:
            llm_state["rejected"].append(
                "llm_config.edit is only applied in single-note mode; split_sections keeps tool-generated section files unchanged"
            )

        saved_paths: list[str] = []
        site_map_content = ""
        site_map_path = ""
        if vault_path:
            folder = Path(vault_path) / _safe_filename(title)
            folder.mkdir(parents=True, exist_ok=True)
            for fname, content_str in files:
                out = folder / fname
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(content_str, encoding="utf-8")
                saved_paths.append(str(out))
                if fname.endswith(" - Site Map.md"):
                    site_map_content = content_str
                    site_map_path = str(out)
        else:
            for fname, content_str in files:
                if fname.endswith(" - Site Map.md"):
                    site_map_content = content_str
                    break

        return {
            "success": True,
            "title": title,
            "content": files[0][1] if files else "",
            "agent_context": agent_context,
            "site_map": site_map_content,
            "structured_data": _build_structured_data(result, None, normalized_llm["structured_data_limit"]) if normalized_llm["include_structured_data"] else None,
            "applied_llm_config": llm_state,
            "browser_context": result.browser_context,
            "path": str(Path(vault_path) / _safe_filename(title)) if vault_path else "",
            "site_map_path": site_map_path,
            "paths": saved_paths,
            "url": url,
            "tags": tags,
            "entities": [],
            "error": None,
        }

    # ── Single-file mode (default) ────────────────────────────────────────────
    note = formatter.format(
        result,
        note_title=requested_title,
        from_url=from_url,
        from_title=from_title,
    )

    llm_state = _apply_llm_config_to_note(note, formatter, normalized_llm)

    if extra_tags:
        existing = note.frontmatter.get("tags", [])
        note.frontmatter["tags"] = list(dict.fromkeys(existing + extra_tags))[:MAX_LLM_TAGS]

    content = note.render()
    title = note.frontmatter.get("title", "Untitled")
    tags = note.frontmatter.get("tags", [])
    entities = note.frontmatter.get("entities", [])
    site_map_content = ""
    site_map_path = ""
    if site_map_config:
        site_map_note = formatter.build_site_map(
            result,
            note_title=title,
            site_map_config=site_map_config,
        )
        site_map_content = site_map_note.render()

    saved_path = ""
    if vault_path:
        vault = Path(vault_path)
        vault.mkdir(parents=True, exist_ok=True)
        file_path = vault / f"{_safe_filename(title)}.md"
        file_path.write_text(content, encoding="utf-8")
        saved_path = str(file_path)
        if site_map_content:
            map_path = vault / f"{_safe_filename(f'{title} - Site Map')}.md"
            map_path.write_text(site_map_content, encoding="utf-8")
            site_map_path = str(map_path)

    return {
        "success": True,
        "title": title,
        "content": content,
        "agent_context": agent_context,
        "site_map": site_map_content,
        "structured_data": _build_structured_data(result, note, normalized_llm["structured_data_limit"]) if normalized_llm["include_structured_data"] else None,
        "applied_llm_config": llm_state,
        "browser_context": result.browser_context,
        "path": saved_path,
        "site_map_path": site_map_path,
        "url": url,
        "tags": tags,
        "entities": entities,
        "error": None,
    }


def _safe_filename(title: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title).strip(". ")
    return safe[:200] or "Untitled"


def _normalize_llm_config(llm_config: dict) -> dict:
    if not isinstance(llm_config, dict):
        raise ValueError("llm_config must be an object/dict")

    rejected: list[str] = []
    user_approved_edits = bool(llm_config.get("user_approved_edits", False))
    include_structured_data = bool(llm_config.get("include_structured_data", False))
    structured_data_limit = llm_config.get("structured_data_limit", 10)
    try:
        structured_data_limit = int(structured_data_limit)
    except (TypeError, ValueError):
        structured_data_limit = 10
    structured_data_limit = max(1, min(MAX_LLM_STRUCTURED_ITEMS, structured_data_limit))

    edit = llm_config.get("edit") or {}
    if not isinstance(edit, dict):
        raise ValueError("llm_config.edit must be an object/dict")

    include_sections, section_rejections = _normalize_section_list(edit.get("include_sections") or [], "include_sections")
    exclude_sections, exclude_rejections = _normalize_section_list(edit.get("exclude_sections") or [], "exclude_sections")
    add_tags, add_tag_rejections = _normalize_tag_list(edit.get("add_tags") or [], "add_tags")
    remove_tags, remove_tag_rejections = _normalize_tag_list(edit.get("remove_tags") or [], "remove_tags")
    frontmatter_fields, frontmatter_rejections = _normalize_frontmatter_fields(edit.get("frontmatter_fields") or {})
    rejected.extend(section_rejections)
    rejected.extend(exclude_rejections)
    rejected.extend(add_tag_rejections)
    rejected.extend(remove_tag_rejections)
    rejected.extend(frontmatter_rejections)

    normalized_edit = {
        "title": _sanitize_title(edit.get("title", "")),
        "add_tags": add_tags,
        "remove_tags": remove_tags,
        "frontmatter_fields": frontmatter_fields,
        "include_sections": include_sections,
        "exclude_sections": exclude_sections,
    }

    if _llm_has_edits({"edit": normalized_edit}) and not user_approved_edits:
        rejected.append(
            "llm_config.edit requires explicit user approval; set llm_config.user_approved_edits=true to allow content changes"
        )
        normalized_edit = {
            "title": "",
            "add_tags": [],
            "remove_tags": [],
            "frontmatter_fields": {},
            "include_sections": [],
            "exclude_sections": [],
        }

    return {
        "user_approved_edits": user_approved_edits,
        "include_structured_data": include_structured_data,
        "structured_data_limit": structured_data_limit,
        "rejected": rejected,
        "edit": normalized_edit,
    }


def _normalize_section_list(raw_sections: list[Any], field_name: str) -> tuple[list[str], list[str]]:
    if not isinstance(raw_sections, list):
        raise ValueError("include_sections/exclude_sections must be arrays")

    sections: list[str] = []
    rejected: list[str] = []
    for value in raw_sections:
        section = str(value).strip().lower()
        if section in LLM_SECTION_HEADINGS and section not in sections:
            sections.append(section)
        elif section:
            rejected.append(f"{field_name}.{section} is not an editable section")
    return sections, rejected


def _normalize_tag_list(raw_tags: list[Any], field_name: str) -> tuple[list[str], list[str]]:
    if not isinstance(raw_tags, list):
        raise ValueError("add_tags/remove_tags must be arrays")

    tags: list[str] = []
    rejected: list[str] = []
    for value in raw_tags:
        tag = _normalize_tag(str(value))
        if tag and tag not in tags:
            tags.append(tag)
        elif str(value).strip():
            rejected.append(f"{field_name}.{value} is not a valid tag")
    return tags, rejected


def _normalize_tag(raw_tag: str) -> str:
    tag = raw_tag.strip().lower()
    tag = re.sub(r"[^\w\s-]", " ", tag, flags=re.UNICODE)
    tag = re.sub(r"[_\s]+", "-", tag)
    tag = re.sub(r"-+", "-", tag).strip("-")
    if not tag or len(tag) < 2 or len(tag) > 40 or re.fullmatch(r"\d+", tag):
        return ""
    return tag


def _normalize_frontmatter_fields(raw_fields: dict) -> tuple[dict, list[str]]:
    if not isinstance(raw_fields, dict):
        raise ValueError("frontmatter_fields must be an object/dict")

    fields = {}
    rejected: list[str] = []
    for key, value in raw_fields.items():
        safe_key = re.sub(r"[^a-z0-9_-]", "", str(key).strip().lower())
        if not safe_key:
            rejected.append(f"frontmatter.{key} has an invalid key")
            continue
        if safe_key in PROTECTED_FRONTMATTER_FIELDS:
            rejected.append(f"frontmatter.{safe_key} is protected")
            continue
        normalized_value = _normalize_frontmatter_value(value)
        if normalized_value is not None:
            fields[safe_key] = normalized_value
        else:
            rejected.append(f"frontmatter.{safe_key} has an unsupported value")
        if len(fields) >= MAX_LLM_FRONTMATTER_ITEMS:
            break
    return fields, rejected


def _normalize_frontmatter_value(value: Any):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().replace("\n", " ")
        return text[:240] if text else None
    if isinstance(value, list):
        items = []
        for item in value[:MAX_LLM_FRONTMATTER_ITEMS]:
            if isinstance(item, (str, int, float, bool)):
                text = str(item).strip().replace("\n", " ")
                if text:
                    items.append(text[:120])
        return items or None
    return None


def _sanitize_title(raw_title: Any) -> str:
    if raw_title is None:
        return ""
    title = re.sub(r"\s+", " ", str(raw_title)).strip()
    title = re.sub(r"[\r\n\t]+", " ", title)
    title = re.sub(r"[\\/*?:\"<>|]", "", title)
    return title[:160]


def _llm_has_edits(llm_config: dict) -> bool:
    edit = llm_config.get("edit", {})
    return any([
        edit.get("title"),
        edit.get("add_tags"),
        edit.get("remove_tags"),
        edit.get("frontmatter_fields"),
        edit.get("include_sections"),
        edit.get("exclude_sections"),
    ])


def _apply_llm_config_to_note(note, formatter: ObsidianFormatter, llm_config: dict) -> dict:
    state = {
        "accepted": [],
        "rejected": list(llm_config.get("rejected", [])),
        "protected_frontmatter_fields": sorted(PROTECTED_FRONTMATTER_FIELDS),
        "editable_sections": list(LLM_SECTION_HEADINGS.keys()),
    }

    if llm_config.get("include_structured_data"):
        state["accepted"].append("include_structured_data")
    if llm_config.get("user_approved_edits") and _llm_has_edits(llm_config):
        state["accepted"].append("user_approved_edits")

    edit = llm_config.get("edit", {})

    if edit.get("title"):
        note.frontmatter["title"] = edit["title"]
        note.body = _replace_note_title(note.body, edit["title"])
        state["accepted"].append("edit.title")

    if edit.get("add_tags") or edit.get("remove_tags"):
        final_tags = []
        for tag in note.frontmatter.get("tags", []):
            normalized = formatter._normalize_tag(tag)
            if normalized and normalized not in final_tags:
                final_tags.append(normalized)
        for tag in edit.get("add_tags", []):
            if tag not in final_tags:
                final_tags.append(tag)
        remove_set = set(edit.get("remove_tags", []))
        final_tags = [tag for tag in final_tags if tag not in remove_set][:MAX_LLM_TAGS]
        note.frontmatter["tags"] = final_tags
        if edit.get("add_tags"):
            state["accepted"].append("edit.add_tags")
        if edit.get("remove_tags"):
            state["accepted"].append("edit.remove_tags")

    if edit.get("frontmatter_fields"):
        for key, value in edit["frontmatter_fields"].items():
            if key in PROTECTED_FRONTMATTER_FIELDS:
                state["rejected"].append(f"frontmatter.{key} is protected")
                continue
            note.frontmatter[key] = value
        state["accepted"].append("edit.frontmatter_fields")

    if edit.get("include_sections") or edit.get("exclude_sections"):
        filtered_body = _filter_note_sections(
            note.body,
            include_sections=edit.get("include_sections", []),
            exclude_sections=edit.get("exclude_sections", []),
        )
        if filtered_body:
            note.body = filtered_body
            if edit.get("include_sections"):
                state["accepted"].append("edit.include_sections")
            if edit.get("exclude_sections"):
                state["accepted"].append("edit.exclude_sections")
        else:
            state["rejected"].append("section filters would remove all editable sections")

    return state


def _replace_note_title(body: str, title: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# "):
            lines[index] = f"# {title}"
            return "\n".join(lines)
    return f"# {title}\n\n{body}".strip()


def _filter_note_sections(body: str, include_sections: list[str], exclude_sections: list[str]) -> str:
    if not include_sections and not exclude_sections:
        return body

    lines = body.splitlines()
    if not lines:
        return body

    title_line = lines[0] if lines[0].startswith("# ") else ""
    remaining = lines[1:] if title_line else lines[:]
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_key = ""
    current_lines: list[str] = []

    heading_to_key = {heading: key for key, heading in LLM_SECTION_HEADINGS.items()}

    for line in remaining:
        key = heading_to_key.get(line.strip())
        if key:
            if current_key:
                sections.append((current_key, current_lines))
            elif current_lines:
                preamble = current_lines
            current_key = key
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_key:
        sections.append((current_key, current_lines))
    elif current_lines:
        preamble = current_lines

    keep_keys = set(include_sections) if include_sections else set(LLM_SECTION_HEADINGS.keys())
    keep_keys -= set(exclude_sections)
    kept_sections = [block for key, block in sections if key in keep_keys]
    if not kept_sections:
        return ""

    rebuilt: list[str] = []
    if title_line:
        rebuilt.append(title_line)
        rebuilt.append("")
    if preamble:
        rebuilt.extend(preamble)
        if rebuilt and rebuilt[-1] != "":
            rebuilt.append("")
    for block in kept_sections:
        rebuilt.extend(block)
        if rebuilt and rebuilt[-1] != "":
            rebuilt.append("")

    return "\n".join(rebuilt).strip()


def _build_structured_data(result, note, limit: int) -> dict:
    extract = result.extract
    metadata = extract.metadata if extract else None
    layout = extract.layout if extract else None
    interactives = extract.interactives if extract else None

    structured = {
        "page": {
            "url": result.url,
            "status_code": result.status_code,
            "rendered": result.rendered,
            "fetch_error": result.fetch_error,
        },
        "frontmatter": note.frontmatter if note else None,
        "summary": result.summary.summary if result.summary else "",
        "content_excerpt": (result.clean_markdown or "")[:2000],
        "metadata": {
            "title": metadata.title if metadata else "",
            "description": metadata.description if metadata else "",
            "canonical": metadata.canonical if metadata else "",
            "lang": metadata.lang if metadata else "",
            "author": metadata.author if metadata else "",
            "keywords": (metadata.keywords if metadata else [])[:limit],
        },
        "layout": {
            "framework": layout.framework if layout else "static",
            "has_shadow_dom": layout.has_shadow_dom if layout else False,
            "sections": [
                {
                    "tag": section.tag,
                    "name": section.name,
                    "heading": section.heading,
                    "role": section.role,
                    "links_count": len(section.links),
                }
                for section in (layout.sections if layout else [])[:limit]
            ],
        },
        "links": {
            "internal": (extract.links.internal if extract else [])[:limit],
            "external": (extract.links.external if extract else [])[:limit],
            "internal_count": len(extract.links.internal) if extract else 0,
            "external_count": len(extract.links.external) if extract else 0,
        },
        "interactives": {
            "buttons": (interactives.buttons if interactives else [])[:limit],
            "inputs": (interactives.inputs if interactives else [])[:limit],
            "forms": (interactives.forms if interactives else [])[:limit],
            "nav_links": (interactives.nav_links if interactives else [])[:limit],
        },
        "tool_rules": {
            "editable_sections": list(LLM_SECTION_HEADINGS.keys()),
            "protected_frontmatter_fields": sorted(PROTECTED_FRONTMATTER_FIELDS),
            "user_approved_edits_required": True,
        },
    }
    return structured
