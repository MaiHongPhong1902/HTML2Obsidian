# HTML2Obsidian

Fetch any URL and produce structured [Obsidian](https://obsidian.md/) Markdown notes — ready for LLM tool calling and knowledge-graph building.

---

## Features

| | |
|---|---|
| **YAML frontmatter** | title, url, domain, smart tags, entities, date |
| **[[WikiLinks]]** | auto-extracted named entities as Obsidian graph nodes |
| **🏗️ Page Structure** | layout sections table (`<header>`, `<nav>`, `<main>`, …) |
| **🖱️ Interactive Elements** | buttons, inputs, forms, nav links with CSS selectors |
| **🤖 Agent Context** | compact snapshot with page type, likely actions, priority links, and key controls |
| **🌲 Site Tree Map** | optional dedicated note with hierarchical URL tree, flat table, or both |
| **🏷️ Smart Auto Tags** | combines domain hints, metadata keywords, URL structure, and page signals |
| **📑 Split-note mode** | one `.md` per page region in `vault/{Title}/` subfolder |
| **SPA support** | Playwright renders React / Vue / Next.js before extraction |
| **YouTube** | channel, views, likes, duration, related videos — no API key |
| **Browser profile** | reuse Chrome / Edge / Firefox cookies and login sessions |
| **LLM summarisation** | optional small-model pre-summary (Ollama / OpenAI-compatible) |

---

## Installation

```bash
pip install -r requirements.txt

# Playwright browsers (only needed when render_js=True)
playwright install chromium

# Optional: spaCy NER for richer WikiLinks
python -m spacy download en_core_web_sm
```

---

## CLI

```bash
# Static page (fast, no browser)
python note.py --vault ./vault --no-js https://en.wikipedia.org/wiki/Python

# JS-rendered SPA
python note.py --vault ./vault https://github.com/owner/repo

# Split into sub-notes per page section
python note.py --vault ./vault --split https://docs.github.com/en

# Generate a dedicated site tree map
python note.py --vault ./vault --site-map --site-map-style both https://docs.github.com/en

# Reuse browser profile (logged-in cookies)
python note.py --vault ./vault --profile chrome https://mail.google.com

# Custom title + extra tags
python note.py --vault ./vault --title "My Note" --tags research ai https://example.com

# YouTube video
python note.py --vault ./vault "https://www.youtube.com/watch?v=VIDEO_ID"

# Print to stdout (no vault)
python note.py https://example.com
```

### CLI Reference

| Argument | Description |
|---|---|
| `url` | URL to fetch (positional, last) |
| `-o`, `--vault DIR` | Obsidian vault directory. Omit to print to stdout |
| `-t`, `--title TITLE` | Custom note title (auto-detected if omitted) |
| `--no-js` | Skip Playwright — faster for static pages |
| `--tags TAG …` | Extra frontmatter tags |
| `--profile PROFILE` | Browser profile: `chrome` \| `edge` \| `firefox` \| `/abs/path` |
| `--split` | Split note into sub-notes by page section |
| `--site-map` | Generate a dedicated site map note |
| `--site-map-style STYLE` | Site map rendering: `tree` \| `table` \| `both` |
| `--site-map-depth N` | Maximum URL depth to expand in tree mode |
| `--site-map-links N` | Maximum internal links to include in the site map |
| `--site-map-external-links N` | Maximum external links to include in the site map |

---

## Split-note mode

`--split` saves multiple linked files into `vault/{Title}/` instead of a single flat note:

```
vault/
└── GitHub Docs/
    ├── GitHub Docs.md                        ← index + relationships
    ├── GitHub Docs - Navigation.md           ← <nav> section
    ├── GitHub Docs - Main.md                 ← <main> section (full content)
    ├── GitHub Docs - Footer.md               ← <footer> section
    └── GitHub Docs - Interactive Elements.md ← all buttons / inputs / forms
```

File names follow `{Title} - {Section}` so WikiLinks are **unique across the entire vault** — even when multiple sites share section names like "Navigation" or "Footer".

Sub-notes link back to their parent:

```yaml
---
title: GitHub Docs - Navigation
parent: "[[GitHub Docs]]"
section_tag: nav
page: "https://docs.github.com/en"
tags:
  - web-section
---
```

---

## Python API

See [API-docs.md](API-docs.md) for a dedicated API reference.

```python
from tools import create_obsidian_note, TOOL_SCHEMA

# Single note returned as string
result = create_obsidian_note(url="https://en.wikipedia.org/wiki/Obsidian")
print(result["content"])

# Save to vault
result = create_obsidian_note(
    url="https://en.wikipedia.org/wiki/Obsidian",
    vault_path="./my-vault",
)
print(result["path"])   # ./my-vault/Obsidian.md

# Split-note mode
result = create_obsidian_note(
    url="https://docs.github.com/en",
    vault_path="./my-vault",
    split_sections=True,
)
print(result["path"])   # ./my-vault/GitHub Docs/
print(result["paths"])  # list of all saved .md files

# Add a hierarchical site map note
result = create_obsidian_note(
    url="https://docs.github.com/en",
    include_site_map=True,
    site_map_style="tree",
    site_map_max_depth=3,
)
print(result["site_map"])

# LLM-safe structured output + constrained edits
result = create_obsidian_note(
    url="https://example.com",
    render_js=False,
    llm_config={
        "user_approved_edits": True,
        "include_structured_data": True,
        "structured_data_limit": 8,
        "edit": {
            "title": "Example Agent Note",
            "add_tags": ["llm-ready", "research"],
            "frontmatter_fields": {"status": "reviewed"},
            "include_sections": ["agent_snapshot", "content"],
        },
    },
)
print(result["structured_data"])
print(result["applied_llm_config"])
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | **required** | Page URL |
| `vault_path` | `str` | `""` | Vault directory. Empty = return content only |
| `note_title` | `str` | `""` | Custom title. Empty = auto-detect from page |
| `render_js` | `bool` | `True` | Use Playwright for JS rendering |
| `extra_tags` | `list[str]` | `[]` | Additional frontmatter tags |
| `from_url` | `str` | `""` | Source URL for backlink |
| `from_title` | `str` | `""` | Title of the source page |
| `browser_profile` | `str` | `""` | Browser profile shortcut or absolute path |
| `split_sections` | `bool` | `False` | Split into sub-notes per page section |
| `include_site_map` | `bool` | `False` | Generate a dedicated site map note |
| `site_map_style` | `str` | `"tree"` | `tree`, `table`, or `both` |
| `site_map_max_depth` | `int` | `3` | Maximum URL depth to expand in tree mode |
| `site_map_max_internal_links` | `int` | `120` | Maximum internal links to include in the site map |
| `site_map_max_external_links` | `int` | `30` | Maximum external links to include in the site map |
| `llm_config` | `dict` | `{}` | LLM-safe structured output + constrained edit rules; `llm_config.edit` requires `user_approved_edits=True` |

### Return value

```python
{
    "success":  bool,
    "title":    str,         # note title
    "content":  str,         # Markdown of index/main note
    "agent_context": str,    # compact context optimized for agent consumption
    "site_map": str,         # dedicated site/tree map note content
    "structured_data": dict | None,  # LLM-readable metadata/layout/link snapshot
    "applied_llm_config": dict,      # accepted/rejected LLM-safe edits
    "path":     str,         # saved file path or folder (split mode)
    "site_map_path": str,    # saved site map file path
    "paths":    list[str],   # all saved files (split mode only)
    "url":      str,
    "tags":     list[str],
    "entities": list[str],
    "error":    str | None,
}
```

---

## LLM Tool Calling

`TOOL_SCHEMA` is OpenAI / Anthropic / Ollama compatible:

```python
from tools import TOOL_SCHEMA
import openai

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Read https://example.com, return structured data, and keep only the agent snapshot and content sections"}],
    tools=[{"type": "function", "function": TOOL_SCHEMA}],
)

# Execute the tool call
import json
from tools import create_obsidian_note

args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
result = create_obsidian_note(**args)

# The tool enforces its own rules:
# - protected frontmatter fields like url/domain/tags cannot be overwritten directly
# - any llm_config.edit change requires explicit user approval via llm_config["user_approved_edits"] = True
# - only whitelisted note sections can be included/excluded
# - invalid or blocked edits are reported in result["applied_llm_config"]["rejected"]
```

---

## Browser Profile (Authenticated Pages)

Reuse an existing browser so the tool can access login-required pages:

```python
result = create_obsidian_note(
    url="https://github.com/notifications",
    vault_path="./vault",
    browser_profile="chrome",
)
```

| Shortcut | Profile directory |
|---|---|
| `chrome` | `%LOCALAPPDATA%\Google\Chrome\User Data` |
| `chrome-dev` | `%LOCALAPPDATA%\Google\Chrome Dev\User Data` |
| `edge` | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| `firefox` | `%APPDATA%\Mozilla\Firefox\Profiles\*.default*` |

Or pass an absolute path to any Chromium user-data directory.

> **Note:** Close Chrome / Edge before running — only one process can hold a profile lock at a time.

---

## Interactive Elements

Every note includes a `## 🖱️ Interactive Elements` section with CSS selectors ready for Playwright automation:

```markdown
**Navigation links:**
| Label | href | selector |
|-------|------|----------|
| [[Explore]] | `/explore` | `nav a[href="/explore"]` |

**Buttons:**
| Label | tag | type | id | selector |
|-------|-----|------|----|----------|
| [[Sign up]] | `a` | `—` | `—` | `a[href="/signup"].btn` |

**Input fields:**
| type | name / id | placeholder | required | selector |
|------|-----------|-------------|----------|----------|
| `text` | `q` | Search | | `input[name="q"][type="text"]` |
```

---

## Optional: LLM Summarisation

Pre-summarise content with a small local model before passing to your main LLM:

```python
from tools.pipeline import BrowserPipeline

pipeline = BrowserPipeline(
    render_js=True,
    summarize=True,
    summarizer_provider="ollama",
    summarizer_model="llama3.2:3b",
    max_summary_words=300,
)
result = pipeline.run("https://example.com")
print(result.summary.summary)
```

| Provider | Value | Notes |
|---|---|---|
| Ollama (local) | `"ollama"` | Default — `http://localhost:11434` |
| OpenAI-compatible | `"openai"` | Set `api_key` and `base_url` |

---

## Package Structure

```
tools/
├── __init__.py            # Exports: create_obsidian_note, TOOL_SCHEMA, ObsidianNote
├── obsidian_tool.py       # Tool entry point + TOOL_SCHEMA
├── obsidian_formatter.py  # PipelineResult → ObsidianNote / split sub-notes
├── pipeline.py            # fetch → extract → clean → summarize
├── fetcher.py             # Playwright (JS / profile) or httpx (static)
├── extractor.py           # Layout, interactive elements, metadata, links, YouTubeExtractor
├── cleaner.py             # HTML → clean Markdown
└── summarizer.py          # Optional small-LLM pre-summarisation
```

---

## Dependencies

| Library | Purpose |
|---|---|
| `httpx` | Static HTTP fetching |
| `playwright` | JS rendering + browser profile |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `trafilatura` | Main article extraction |
| `markitdown` | HTML / PDF / DOCX → Markdown |
| `spacy` *(optional)* | NER for richer WikiLinks |
