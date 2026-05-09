# Browser → Obsidian Tool

A self-contained Python package that fetches any URL and produces a structured [Obsidian](https://obsidian.md/) Markdown note — ready for LLM tool calling.

---

## Features

- **YAML frontmatter** — title, url, tags, entities, date
- **[[WikiLinks]]** — auto-extracted named entities linked as Obsidian internal links
- **Relationships & References** — backlinks, outbound links, images, iframes
- **🖱️ Interactive Elements** — buttons, inputs, forms, nav links with CSS selectors for agent use
- **SPA support** — Playwright renders React / Vue / Next.js pages before extraction
- **YouTube** — channel, views, likes, duration, description, related videos (no API key)
- **Wikipedia / arXiv / GitHub** — metadata-aware extraction
- **Browser profile** — reuse Chrome/Edge/Firefox cookies and login sessions
- **Optional summarisation** — small LLM (Ollama / OpenAI-compatible) pre-summarises content before the main LLM sees it

---

## Installation

```bash
pip install -r requirements.txt

# Install Playwright browsers (only needed when render_js=True)
playwright install chromium

# Optional: spaCy NER model for richer WikiLinks
python -m spacy download en_core_web_sm
```

---

## Quick Start

```python
from tools import create_obsidian_note, TOOL_SCHEMA

# Returns a dict — no file saved
result = create_obsidian_note(url="https://en.wikipedia.org/wiki/Obsidian")
print(result["content"])

# Save to vault
result = create_obsidian_note(
    url="https://en.wikipedia.org/wiki/Obsidian",
    vault_path="./my-vault",
)
print(result["path"])   # ./my-vault/Obsidian.md
```

### CLI

```bash
# Static page (fast)
python note.py --vault ./vault --no-js https://en.wikipedia.org/wiki/Python

# SPA / JS-rendered page
python note.py --vault ./vault https://github.com/owner/repo

# YouTube video
python note.py --vault ./vault "https://www.youtube.com/watch?v=VIDEO_ID"

# Reuse browser profile (logged-in cookies)
python note.py --vault ./vault --profile chrome https://mail.google.com

# Custom title and extra tags
python note.py --vault ./vault --title "My Note" --tags research ai https://example.com
```

---

## LLM Tool Calling

Pass `TOOL_SCHEMA` directly to any OpenAI-compatible API:

```python
from tools import TOOL_SCHEMA
import openai

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarise https://arxiv.org/abs/2307.09288 as an Obsidian note"}],
    tools=[{"type": "function", "function": TOOL_SCHEMA}],
)
```

When the model calls the tool, execute it:

```python
import json
from tools import create_obsidian_note

tool_call = response.choices[0].message.tool_calls[0]
args = json.loads(tool_call.function.arguments)
result = create_obsidian_note(**args)
```

---

## `create_obsidian_note()` Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | **required** | Page URL (must start with `http/https`) |
| `vault_path` | `str` | `""` | Obsidian vault directory. Empty = return content only, no file saved |
| `note_title` | `str` | `""` | Custom title. Empty = auto-detect from page |
| `render_js` | `bool` | `True` | Use Playwright to render JavaScript. Set `False` for faster static pages |
| `extra_tags` | `list[str]` | `[]` | Additional frontmatter tags |
| `from_url` | `str` | `""` | Source URL for backlink (if navigated from another page) |
| `from_title` | `str` | `""` | Title of the source page |
| `browser_profile` | `str` | `""` | Reuse browser profile for cookies/sessions. Shortcuts: `chrome`, `edge`, `firefox`, or absolute path |

### Return value

```python
{
    "success":  bool,
    "title":    str,        # note title
    "content":  str,        # full Markdown with frontmatter
    "path":     str,        # saved file path (empty if not saved)
    "url":      str,        # original URL
    "tags":     list[str],  # assigned tags
    "entities": list[str],  # extracted WikiLink entities
    "error":    str | None, # error message if failed
}
```

---

## Browser Profile (Authenticated Pages)

Reuse an existing browser profile so the tool can access pages that require login:

```python
result = create_obsidian_note(
    url="https://mail.google.com",
    vault_path="./vault",
    browser_profile="chrome",   # shortcut
)
```

Supported shortcuts (Windows paths resolved automatically):

| Shortcut | Profile directory |
|---|---|
| `chrome` | `%LOCALAPPDATA%\Google\Chrome\User Data` |
| `chrome-dev` | `%LOCALAPPDATA%\Google\Chrome Dev\User Data` |
| `edge` | `%LOCALAPPDATA%\Microsoft\Edge\User Data` |
| `firefox` | `%APPDATA%\Mozilla\Firefox\Profiles\*.default*` |

Or pass an absolute path to any Chromium-based user-data directory.

> **Note:** Chrome/Edge must be fully closed before running, since only one process can lock a profile at a time.

---

## Interactive Elements

Every note includes a `## 🖱️ Interactive Elements` section with tables of buttons, inputs, and nav links — each with a ready-to-use CSS selector:

```markdown
## 🖱️ Interactive Elements

**Buttons:**
| Label | tag | type | id | selector |
|-------|-----|------|----|----------|
| Đăng ký | `button` | `button` | `—` | `button[aria-label="Đăng ký TheAnh96."].ytSpecButtonShape` |
| Chia sẻ | `button` | `button` | `—` | `button[aria-label="Chia sẻ"].ytSpecButtonShape` |

**Input fields:**
| type | name / id | placeholder | aria-label | selector |
|------|-----------|-------------|------------|----------|
| `text` | `search_query` | Tìm kiếm | — | `input[name="search_query"][type="text"]` |
```

An agent can use these selectors directly with Playwright to click, type, or navigate.

---

## Optional: Summarisation

Pre-summarise page content with a small local model before passing to your main LLM:

```python
from tools.pipeline import BrowserPipeline

pipeline = BrowserPipeline(
    render_js=True,
    summarize=True,
    summarizer_provider="ollama",   # or "openai"
    summarizer_model="llama3.2:3b",
    max_summary_words=300,
)
result = pipeline.run("https://example.com")
print(result.summary)
```

Supported providers:

| Provider | Value | Notes |
|---|---|---|
| Ollama (local) | `"ollama"` | Default — `http://localhost:11434` |
| OpenAI-compatible | `"openai"` | Pass `api_key` and `base_url` |

---

## Package Structure

```
tools/
├── __init__.py            # Exports: create_obsidian_note, TOOL_SCHEMA, ObsidianNote
├── obsidian_tool.py       # Main tool function + TOOL_SCHEMA
├── obsidian_formatter.py  # PipelineResult → ObsidianNote (frontmatter, WikiLinks, …)
├── pipeline.py            # Orchestrates fetch → extract → clean → summarize
├── fetcher.py             # HTTP fetching: Playwright (JS/profile) or httpx (static)
├── extractor.py           # Metadata, links, images, iframes, layout, interactive elements
│                          # Also contains: YouTubeExtractor (no API key)
├── cleaner.py             # HTML → clean Markdown (markitdown / trafilatura / BS4)
└── summarizer.py          # Optional small-LLM pre-summarisation
```

---

## CLI Reference

```
usage: note.py [-o DIR] [-t TITLE] [--no-js] [--tags ...] [--profile PROFILE] url

positional arguments:
  url                   URL to fetch

options:
  -o, --vault DIR       Obsidian vault directory (default: print to stdout)
  -t, --title TITLE     Custom note title
  --no-js               Skip JS rendering (faster, for static pages)
  --tags TAG [TAG ...]  Extra frontmatter tags
  --profile PROFILE     Browser profile: chrome | edge | firefox | /abs/path
```

---

## Dependencies

| Library | Purpose |
|---|---|
| `httpx` | Fast static HTTP fetching |
| `playwright` | JS rendering + browser profile support |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `trafilatura` | Main article extraction |
| `markitdown` | HTML / PDF / DOCX → Markdown |
| `spacy` *(optional)* | NER for richer WikiLinks |


A self-contained Python package that fetches any URL and produces a structured [Obsidian](https://obsidian.md/) Markdown note — ready for LLM tool calling.

---

## Features

- **YAML frontmatter** — title, url, tags, entities, date
- **[[WikiLinks]]** — auto-extracted named entities linked as Obsidian internal links
- **Relationships & References** — backlinks, outbound links, images, iframes
- **SPA support** — Playwright renders React / Vue / Next.js pages before extraction
- **YouTube** — channel, views, likes, duration, description, related videos (no API key)
- **Wikipedia / arXiv / GitHub** — metadata-aware extraction
- **Optional summarisation** — small LLM (Ollama / OpenAI-compatible) pre-summarises content before the main LLM sees it

---

## Installation

```bash
pip install -r requirements.txt

# Install Playwright browsers (only needed when render_js=True)
playwright install chromium

# Optional: spaCy NER model for richer WikiLinks
python -m spacy download en_core_web_sm
```

---

## Quick Start

```python
from tools import create_obsidian_note, TOOL_SCHEMA

# Returns a dict — no file saved
result = create_obsidian_note(url="https://en.wikipedia.org/wiki/Obsidian")
print(result["content"])

# Save to vault
result = create_obsidian_note(
    url="https://en.wikipedia.org/wiki/Obsidian",
    vault_path="./my-vault",
)
print(result["path"])   # ./my-vault/Obsidian.md
```

---

## LLM Tool Calling

Pass `TOOL_SCHEMA` directly to any OpenAI-compatible API:

```python
from tools import TOOL_SCHEMA
import openai

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Summarise https://arxiv.org/abs/2307.09288 as an Obsidian note"}],
    tools=[{"type": "function", "function": TOOL_SCHEMA}],
)
```

When the model calls the tool, execute it:

```python
import json
from tools import create_obsidian_note

tool_call = response.choices[0].message.tool_calls[0]
args = json.loads(tool_call.function.arguments)
result = create_obsidian_note(**args)
```

---

## `create_obsidian_note()` Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | **required** | Page URL (must start with `http/https`) |
| `vault_path` | `str` | `""` | Obsidian vault directory. Empty = return content only, no file saved |
| `note_title` | `str` | `""` | Custom title. Empty = auto-detect from page |
| `render_js` | `bool` | `True` | Use Playwright to render JavaScript. Set `False` for faster static pages |
| `extra_tags` | `list[str]` | `[]` | Additional frontmatter tags |
| `from_url` | `str` | `""` | Source URL for backlink (if navigated from another page) |
| `from_title` | `str` | `""` | Title of the source page |

### Return value

```python
{
    "success":  bool,
    "title":    str,        # note title
    "content":  str,        # full Markdown with frontmatter
    "path":     str,        # saved file path (empty if not saved)
    "url":      str,        # original URL
    "tags":     list[str],  # assigned tags
    "entities": list[str],  # extracted WikiLink entities
    "error":    str | None, # error message if failed
}
```

---

## Optional: Summarisation

Pre-summarise page content with a small local model before passing to your main LLM:

```python
from tools.summarizer import PageSummarizer
from tools.pipeline import BrowserPipeline

pipeline = BrowserPipeline(
    render_js=True,
    summarizer=PageSummarizer(
        provider="ollama",   # or "openai"
        model="llama3.2:3b",
        max_words=300,
    ),
)
result = pipeline.run("https://example.com")
print(result.summary)
```

Supported providers:

| Provider | Value | Notes |
|---|---|---|
| Ollama (local) | `"ollama"` | Default — `http://localhost:11434` |
| OpenAI-compatible | `"openai"` | Pass `api_key` and `base_url` |

---

## Package Structure

```
tools/
├── __init__.py            # Exports: create_obsidian_note, TOOL_SCHEMA, ObsidianNote
├── obsidian_tool.py       # Main tool function + TOOL_SCHEMA
├── obsidian_formatter.py  # PipelineResult → ObsidianNote (frontmatter, WikiLinks, …)
├── pipeline.py            # Orchestrates fetch → extract → clean → summarize
├── fetcher.py             # HTTP fetching: Playwright (JS) or httpx (static)
├── extractor.py           # Metadata, links, images, iframes, layout
├── cleaner.py             # HTML → clean Markdown (markitdown / trafilatura / BS4)
├── summarizer.py          # Optional small-LLM pre-summarisation
└── youtube_extractor.py   # YouTube metadata without API key
```

---

## Dependencies

| Library | Purpose |
|---|---|
| `httpx` | Fast static HTTP fetching |
| `playwright` | JS rendering for SPA pages |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `trafilatura` | Main article extraction |
| `markitdown` | HTML / PDF / DOCX → Markdown |
| `spacy` *(optional)* | NER for richer WikiLinks |
