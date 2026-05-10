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
| **Low-code / no-code forms** | detects Form.io and OutSystems rendered forms, field keys, labels, validation, and embedded schemas |
| **YouTube** | channel, views, likes, duration, related videos — no API key |
| **Browser profile** | reuse Chrome / Edge / Firefox cookies and login sessions |
| **LLM summarisation** | optional small-model pre-summary (Ollama / OpenAI-compatible) |
| **🔍 DOM Index** | per-fetch semantic index: headings, tables, code blocks, lists, images, key-values, forms |
| **⚡ Element Query** | `query_page_elements()` — CSS selector queries + `QUERY_SCHEMA` for direct LLM tool calling |
| **🌐 Browser Context** | XHR/fetch capture, page metrics, embedded JSON globals, JSON-LD, lazy-image resolution |
| **⏳ wait_for_selector** | pause DOM snapshot until a specific element appears — ensures async content is captured |

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

# Low-code / no-code rendered forms (Form.io, OutSystems)
python note.py --vault ./vault https://example.com/runtime-form

# Split into sub-notes per page section
python note.py --vault ./vault --split https://docs.github.com/en

# Generate a dedicated site tree map (--sitemap is also accepted)
python note.py --vault ./vault --site-map --site-map-style both https://docs.github.com/en

# Reuse browser profile (logged-in cookies)
python note.py --vault ./vault --profile chrome https://mail.google.com

# Use a specific Chrome / Edge profile
python note.py --vault ./vault --profile "chrome:Default" https://mail.google.com
python note.py --vault ./vault --profile "edge:Profile 1" https://example.com

# Load or save Playwright cookies/localStorage state
python note.py --vault ./vault --cookies ./auth-state.json https://example.com
python note.py --vault ./vault --headed --auth-wait 60 --save-cookies ./auth-state.json https://example.com

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
| `--browser-channel CHANNEL` | Browser channel: `chrome`, `msedge`; optional override |
| `--headed` | Launch visible browser window for login/cookie refresh |
| `--auth-wait SECONDS` | Keep headed browser open before snapshot/save so you can finish login |
| `--cookies FILE` | Load Playwright `storage_state` JSON cookies/localStorage |
| `--save-cookies FILE` | Save Playwright `storage_state` JSON after fetch |
| `--split` | Split note into sub-notes by page section |
| `--site-map`, `--sitemap` | Generate a dedicated site map note |
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

See [API-docs.md](API-docs.md) for full reference: parameters, return values, `browser_context` fields, `query_page_elements`, `TOOL_SCHEMA`, `QUERY_SCHEMA`, `BrowserPipeline`, DOM index, and LLM summarisation.

```python
from tools import create_obsidian_note, TOOL_SCHEMA
from tools import query_page_elements, QUERY_SCHEMA

# Save note to vault
result = create_obsidian_note(url="https://example.com", vault_path="./my-vault")
print(result["path"])

# Capture browser context (XHR, metrics, JSON-LD, DOM index)
result = create_obsidian_note(
    url="https://shop.example.com/product/123",
    capture_network=True,
    wait_for_selector=".product-price",
)
print(result["browser_context"]["dom_index"]["headings"])

# Targeted element query (LLM-friendly)
result = query_page_elements(
    url="https://example.com",
    queries={"title": "h1", "price": ".product-price"},
)
print(result["results"])
```

---

## LLM Tool Calling

Two tool schemas — pass directly to OpenAI / Anthropic / Ollama.

```python
from tools import TOOL_SCHEMA, QUERY_SCHEMA
```

- **`TOOL_SCHEMA`** — full note creation via `create_obsidian_note()`
- **`QUERY_SCHEMA`** — targeted element queries via `query_page_elements()`

See [API-docs.md → LLM Tool Calling](API-docs.md#llm-tool-calling) for complete examples.

---

## Browser Profile / Cookies (Authenticated Pages)

Reuse an existing browser so the tool can access login-required pages:

```python
result = create_obsidian_note(
    url="https://github.com/notifications",
    vault_path="./vault",
    browser_profile="chrome:Default",
)
```

| Shortcut | Profile directory |
|---|---|
| `chrome` | `%LOCALAPPDATA%\Google\Chrome\User Data` |
| `chrome-dev` | `%LOCALAPPDATA%\Google\Chrome Dev\User Data` |
| `edge` | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| `firefox` | `%APPDATA%\Mozilla\Firefox\Profiles\*.default*` |

You can append a profile directory name, for example `chrome:Default` or `edge:Profile 1`. You can also pass an absolute Chromium user-data directory, or a profile directory such as `...\User Data\Default`.

For repeatable authenticated scraping, export cookies/localStorage once:

```bash
python note.py --headed --auth-wait 60 --save-cookies ./auth-state.json https://example.com/login
python note.py --vault ./vault --cookies ./auth-state.json https://example.com/private
```

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

Pre-summarise content with a small local model (Ollama / OpenAI-compatible) before passing to your main LLM. See [API-docs.md → LLM Summarisation](API-docs.md#llm-summarisation) for configuration details.

---

## Package Structure

```
tools/
├── __init__.py            # Exports: create_obsidian_note, TOOL_SCHEMA, query_page_elements, QUERY_SCHEMA, ObsidianNote
├── obsidian_tool.py       # Tool entry point + TOOL_SCHEMA + query_page_elements + QUERY_SCHEMA
├── obsidian_formatter.py  # PipelineResult → ObsidianNote / split sub-notes
├── pipeline.py            # fetch → extract → clean → summarize; exposes browser_context
├── fetcher.py             # Playwright (JS / profile / dom_index / network capture) or httpx (static)
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
