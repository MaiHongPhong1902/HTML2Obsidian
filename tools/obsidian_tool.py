"""
tools/obsidian_tool.py — Tool calling module: URL → Obsidian Note.

Usage as an LLM agent tool function:
    from tools import create_obsidian_note, TOOL_SCHEMA
    result = create_obsidian_note(url="https://example.com", vault_path="./vault")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .pipeline import BrowserPipeline
from .obsidian_formatter import ObsidianFormatter

# ──────────────────────────────────────────────────────────────────────────────
# Tool schema — pass directly to OpenAI / Ollama / Anthropic tool calling
# ──────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMA = {
    "name": "create_obsidian_note",
    "description": (
        "Fetch a URL and create an Obsidian Markdown note with YAML frontmatter, "
        "[[WikiLinks]] for key entities, auto-generated domain tags, and Relationships / References sections. "
        "Supports SPA pages (React/Vue/Next.js), Wikipedia, YouTube, GitHub, arXiv."
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
) -> dict:
    """
    Create an Obsidian note from a URL.

    Returns:
        dict:
            success  (bool)  — whether the operation succeeded
            title    (str)   — note title
            content  (str)   — full Markdown content
            path     (str)   — saved file path (empty if not saved)
            url      (str)   — original URL
            tags     (list)  — assigned tags
            entities (list)  — extracted entities
            error    (str)   — error description if failed
    """
    extra_tags = extra_tags or []

    pipeline = BrowserPipeline(render_js=render_js, browser_profile=browser_profile)
    result = pipeline.run(url)

    if result.fetch_error:
        return {
            "success": False,
            "title": "",
            "content": "",
            "path": "",
            "url": url,
            "tags": [],
            "entities": [],
            "error": result.fetch_error,
        }

    formatter = ObsidianFormatter(use_spacy=False)

    # ── Split-sections mode ───────────────────────────────────────────────────
    if split_sections:
        files = formatter.format_split(
            result,
            note_title=note_title or None,
            from_url=from_url,
            from_title=from_title,
        )

        # Infer title and tags from index.md frontmatter (first file)
        _first_content = files[0][1] if files else ""
        _title_match = re.search(r"^title:\s*(.+)$", _first_content, re.MULTILINE)
        title = _title_match.group(1).strip() if _title_match else (note_title or "Untitled")
        _tags_match = re.findall(r"^  - (.+)$", _first_content, re.MULTILINE)
        tags = _tags_match[:10]

        saved_paths: list[str] = []
        if vault_path:
            folder = Path(vault_path) / _safe_filename(title)
            folder.mkdir(parents=True, exist_ok=True)
            for fname, content_str in files:
                out = folder / fname
                out.write_text(content_str, encoding="utf-8")
                saved_paths.append(str(out))

        return {
            "success": True,
            "title": title,
            "content": files[0][1] if files else "",
            "path": str(Path(vault_path) / _safe_filename(title)) if vault_path else "",
            "paths": saved_paths,
            "url": url,
            "tags": tags,
            "entities": [],
            "error": None,
        }

    # ── Single-file mode (default) ────────────────────────────────────────────
    note = formatter.format(
        result,
        note_title=note_title or None,
        from_url=from_url,
        from_title=from_title,
    )

    if extra_tags:
        existing = note.frontmatter.get("tags", [])
        note.frontmatter["tags"] = list(dict.fromkeys(existing + extra_tags))

    content = note.render()
    title = note.frontmatter.get("title", "Untitled")
    tags = note.frontmatter.get("tags", [])
    entities = note.frontmatter.get("entities", [])

    saved_path = ""
    if vault_path:
        vault = Path(vault_path)
        vault.mkdir(parents=True, exist_ok=True)
        file_path = vault / f"{_safe_filename(title)}.md"
        file_path.write_text(content, encoding="utf-8")
        saved_path = str(file_path)

    return {
        "success": True,
        "title": title,
        "content": content,
        "path": saved_path,
        "url": url,
        "tags": tags,
        "entities": entities,
        "error": None,
    }


def _safe_filename(title: str) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "", title).strip(". ")
    return safe[:200] or "Untitled"
