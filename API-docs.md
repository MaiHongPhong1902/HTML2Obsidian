# HTML2Obsidian — API Reference

Full reference for the Python API, tool schemas, and pipeline internals.
→ Back to [README.md](README.md)

---

## Table of Contents

- [Public Exports](#public-exports)
- [create\_obsidian\_note()](#create_obsidian_note)
  - [Parameters](#parameters)
  - [Return value](#return-value)
  - [browser\_context fields](#browser_context-fields)
- [query\_page\_elements()](#query_page_elements)
  - [Parameters](#parameters-1)
  - [Return value](#return-value-1)
- [LLM Tool Calling](#llm-tool-calling)
  - [TOOL\_SCHEMA](#tool_schema--full-note-creation)
  - [QUERY\_SCHEMA](#query_schema--targeted-element-queries)
- [LLM Config](#llm-config)
- [DOM Index](#dom-index)
- [BrowserPipeline](#browserpipeline)
- [LLM Summarisation](#llm-summarisation)

---

## Public Exports

```python
from tools import (
    create_obsidian_note,  # main note-generation function
    TOOL_SCHEMA,           # OpenAI/Anthropic/Ollama function schema for create_obsidian_note
    query_page_elements,   # targeted CSS-selector queries against a live page
    QUERY_SCHEMA,          # function schema for query_page_elements
    ObsidianNote,          # internal rendered note dataclass
)
```

---

## `create_obsidian_note()`

Fetches a URL and produces a structured Obsidian Markdown note.

```python
from tools import create_obsidian_note

# Return content only (no file saved)
result = create_obsidian_note(url="https://en.wikipedia.org/wiki/Obsidian")
print(result["content"])

# Save to vault
result = create_obsidian_note(
    url="https://en.wikipedia.org/wiki/Obsidian",
    vault_path="./my-vault",
)
print(result["path"])   # ./my-vault/Obsidian.md

# Split-note mode — one file per page section
result = create_obsidian_note(
    url="https://docs.github.com/en",
    vault_path="./my-vault",
    split_sections=True,
)
print(result["path"])   # ./my-vault/GitHub Docs/
print(result["paths"])  # list of all saved .md files

# Hierarchical site map note
result = create_obsidian_note(
    url="https://docs.github.com/en",
    include_site_map=True,
    site_map_style="tree",
    site_map_max_depth=3,
)
print(result["site_map"])

# Capture browser context (XHR, metrics, JSON-LD, embedded globals, DOM index)
result = create_obsidian_note(
    url="https://shop.example.com/product/123",
    capture_network=True,
    wait_for_selector=".product-price",
    wait_for_timeout=10.0,
)
print(result["browser_context"]["network_requests"])
print(result["browser_context"]["page_metrics"])
print(result["browser_context"]["dom_index"]["headings"])

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
| `browser_profile` | `str` | `""` | Browser profile shortcut/path. Supports `chrome`, `edge`, `firefox`, `chrome:Default`, `edge:Profile 1` |
| `browser_channel` | `str` | `""` | Optional Playwright browser channel override, e.g. `chrome`, `msedge` |
| `browser_headless` | `bool` | `True` | Set `False` to open a visible browser for login/cookie refresh |
| `storage_state_path` | `str` | `""` | Load cookies/localStorage from a Playwright `storage_state` JSON file |
| `auto_storage_state` | `bool` | `True` | Auto-load saved storage state when `storage_state_path` is empty |
| `save_storage_state_path` | `str` | `""` | Save cookies/localStorage to a Playwright `storage_state` JSON file after fetch |
| `auth_wait_seconds` | `float` | `0.0` | Keep a headed browser open before snapshot/save so manual login can finish |
| `split_sections` | `bool` | `False` | Split into sub-notes per page section |
| `split` | `bool \| None` | `None` | Alias for `split_sections`, matching CLI `--split` |
| `include_site_map` | `bool` | `False` | Generate a dedicated site map note |
| `site_map` | `bool \| None` | `None` | Alias for `include_site_map`, matching CLI `--site-map` / `--sitemap` |
| `site_map_style` | `str` | `"tree"` | `tree`, `table`, or `both` |
| `site_map_max_depth` | `int` | `3` | Maximum URL depth to expand in tree mode |
| `site_map_max_internal_links` | `int` | `120` | Maximum internal links to include in the site map |
| `site_map_max_external_links` | `int` | `30` | Maximum external links to include in the site map |
| `capture_network` | `bool` | `False` | Capture XHR/fetch requests during page load |
| `wait_for_selector` | `str` | `""` | CSS selector to wait for before DOM snapshot — handles async/lazy content |
| `wait_for_timeout` | `float` | `10.0` | Max seconds to wait for `wait_for_selector` |
| `llm_config` | `dict` | `{}` | LLM-safe structured output + constrained edit rules — see [LLM Config](#llm-config) |

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
    "browser_context": dict,         # see browser_context fields below
    "path":     str,         # saved file path or folder (split mode)
    "site_map_path": str,    # saved site map file path
    "paths":    list[str],   # all saved files (split mode only)
    "url":      str,
    "tags":     list[str],
    "entities": list[str],
    "error":    str | None,
}
```

### `browser_context` fields

| Key | Type | Description |
|---|---|---|
| `spa_framework` | `str` | `static` \| `react` \| `vue` \| `angular` \| `next.js` \| `nuxt` \| `formio` \| `outsystems` |
| `page_metrics` | `dict` | `load_time_ms`, `dom_content_loaded_ms`, `dom_nodes`, `images`, `scripts`, `links` |
| `network_requests` | `list` | XHR/fetch calls: `[{url, method, status, content_type}]` (requires `capture_network=True`) |
| `embedded_json` | `dict` | SSR window globals: `__NEXT_DATA__`, `__NUXT__`, `__REDUX_STATE__`, etc. |
| `json_ld` | `list` | Parsed `<script type="application/ld+json">` objects |
| `lazy_images_resolved` | `int` | Count of `data-src` images resolved before snapshot |
| `dom_index` | `dict` | Semantic DOM index — see [DOM Index](#dom-index) |
| `lowcode` | `dict` | Low-code/no-code summary: platform, indicators, rendered component count, schema component count |

---

## `query_page_elements()`

Targeted CSS-selector queries against a live page. Returns matched elements and the DOM index without generating a full note. Ideal for LLM tool calling when only specific elements are needed.

```python
from tools import query_page_elements

result = query_page_elements(
    url="https://shop.example.com/product/123",
    queries={
        "price":   ".product-price",
        "title":   "h1",
        "reviews": ".review-text",
        "images":  "img.product-img",
    },
    attributes=["href", "src", "data-id"],
    wait_for_selector=".product-price",
    wait_for_timeout=10.0,
)

result["results"]      # {"price": [{"text": "$29.99"}], "title": [{"text": "Acme Widget"}], ...}
result["dom_index"]    # headings, tables, code, lists, images, key_values, sections, forms
result["page_metrics"] # load_time_ms, dom_nodes, etc.
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | **required** | Page URL |
| `queries` | `dict` | **required** | `{label: css_selector}` — each returns up to 50 matched elements |
| `attributes` | `list[str]` | `[]` | HTML attributes to include alongside text (e.g. `["href","src"]`) |
| `render_js` | `bool` | `True` | Use Playwright for SPA pages |
| `include_dom_index` | `bool` | `True` | Include pre-built semantic DOM index in result |
| `wait_for_selector` | `str` | `""` | CSS selector to wait for before DOM snapshot |
| `wait_for_timeout` | `float` | `10.0` | Max seconds to wait for `wait_for_selector` |

### Return value

```python
{
    "success":      bool,
    "url":          str,
    "results":      dict,   # {label: [{text, ...attrs}]} — up to 50 matches per selector
    "dom_index":    dict,   # present when include_dom_index=True
    "page_metrics": dict,   # load_time_ms, dom_content_loaded_ms, dom_nodes, images, scripts, links
    "error":        str | None,
}
```

---

## LLM Tool Calling

Two OpenAI / Anthropic / Ollama-compatible tool schemas are exported from `tools`.

### `TOOL_SCHEMA` — full note creation

```python
from tools import TOOL_SCHEMA, create_obsidian_note
import openai, json

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": "Read https://example.com, return structured data, keep only the agent snapshot and content sections",
    }],
    tools=[{"type": "function", "function": TOOL_SCHEMA}],
)

args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
result = create_obsidian_note(**args)

# Tool enforces its own rules:
# - protected frontmatter fields (url, domain, tags) cannot be overwritten
# - llm_config.edit requires user_approved_edits=True
# - only whitelisted sections can be included/excluded
# - rejected edits reported in result["applied_llm_config"]["rejected"]
```

### `QUERY_SCHEMA` — targeted element queries

For when the LLM needs specific elements without a full note:

```python
from tools import QUERY_SCHEMA, query_page_elements
import openai, json

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": "What is the price of the first product on https://shop.example.com?",
    }],
    tools=[{"type": "function", "function": QUERY_SCHEMA}],
)

args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
result = query_page_elements(**args)
# result["results"] → {"price": [{"text": "$29.99"}], ...}
# result["dom_index"] → headings, tables, code, lists, images, key_values, sections, forms
```

---

## LLM Config

`llm_config` is designed for tool-calling scenarios where the model must inspect source data and request constrained note changes.

```python
llm_config = {
    "user_approved_edits": False,    # must be True before any edit is applied
    "include_structured_data": True,
    "structured_data_limit": 8,
    "edit": {
        "title": "Example Agent Note",
        "add_tags": ["llm-ready", "research"],
        "remove_tags": ["web-clip"],
        "frontmatter_fields": {"status": "reviewed"},
        "include_sections": ["agent_snapshot", "content"],
        "exclude_sections": ["references"],
    },
}
```

### Top-Level Controls

| Key | Type | Default | Description |
|---|---|---|---|
| `user_approved_edits` | `bool` | `False` | Must be `True` before any `edit` changes are applied |
| `include_structured_data` | `bool` | `False` | Return structured source data for the LLM to inspect |
| `structured_data_limit` | `int` | `10` | Per-list item cap for structured output (clamped to 1–20) |
| `edit` | `dict` | `{}` | Safe edits applied only when `user_approved_edits=True` |

### Edit Controls

| Key | Type | Description |
|---|---|---|
| `edit.title` | `str` | Replace the note title (sanitized) |
| `edit.add_tags` | `list[str]` | Append tags after auto-tag generation |
| `edit.remove_tags` | `list[str]` | Remove matching tags from final output |
| `edit.frontmatter_fields` | `dict` | Add non-protected frontmatter fields |
| `edit.include_sections` | `list[str]` | Keep only these top-level sections |
| `edit.exclude_sections` | `list[str]` | Remove these top-level sections |

### Editable Section Keys

`summary`, `agent_snapshot`, `page_structure`, `lowcode`, `interactive_elements`, `content`, `relationships`, `references`, `navigation`

### Protected Frontmatter Fields

Cannot be overwritten via `edit.frontmatter_fields`:
`title`, `url`, `domain`, `fetched`, `tags`, `entities`, `from_url`, `framework`, `has_shadow_dom`, `lowcode_platform`, `lowcode_components_count`, `video_id`, `channel`, `upload_date`, `duration`, `map_for`, `last_updated`, `source_page`, `map_style`, `tree_depth`, `internal_links_count`, `external_links_count`

---

## DOM Index

Every Playwright fetch automatically builds a `dom_index` — a semantic snapshot of the page structure. Available in `browser_context["dom_index"]` and in every `query_page_elements()` result.

| Key | Type | Description |
|---|---|---|
| `headings` | `list` | All h1–h6: `{level, text, id, href}` |
| `tables` | `list` | Headers + rows (up to 10 rows/table, 20 tables) |
| `code` | `list` | `pre`/`code` blocks with detected language |
| `lists` | `list` | `ul`/`ol` items (up to 20 items/list, 25 lists) |
| `images` | `list` | `{src, alt, width}` for all `<img>` |
| `key_values` | `list` | `<dl>` definition list pairs `{key, value}` |
| `sections` | `list` | Heading + 200-char preview of following content |
| `forms` | `list` | `{action, method, inputs[]}` for each `<form>` |
| `lowcode_components` | `list` | Rendered Form.io/OutSystems-like components with label, key, type, required, disabled |

SPAs render data asynchronously — use `wait_for_selector` to ensure the snapshot is taken **after** the target content has appeared:

```python
from tools.pipeline import BrowserPipeline

pipeline = BrowserPipeline(
    wait_for_selector="table.results tbody tr",
    wait_for_timeout=8.0,
)
result = pipeline.run("https://example.com/search?q=python")
print(result.browser_context["dom_index"]["tables"])
```

---

## `BrowserPipeline`

Low-level orchestration class: `fetch → extract → clean → summarize`. Use when you need direct access to `PipelineResult` instead of the high-level tool functions.

```python
from tools.pipeline import BrowserPipeline

pipeline = BrowserPipeline(
    render_js=True,
    capture_network=True,
    wait_for_selector=".content",
    wait_for_timeout=10.0,
)
result = pipeline.run("https://example.com")

result.html             # raw HTML
result.markdown         # cleaned Markdown content
result.browser_context  # spa_framework, page_metrics, dom_index, network_requests, ...
result.summary          # SummaryResult if summarize=True
```

### Constructor parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `render_js` | `bool` | `True` | Use Playwright for JS rendering |
| `browser_profile` | `str` | `None` | Reuse authenticated browser profile; supports `chrome:Default`, `edge:Profile 1`, or absolute profile/user-data path |
| `browser_channel` | `str` | `None` | Browser channel override, e.g. `chrome`, `msedge` |
| `browser_headless` | `bool` | `True` | Set `False` for visible login/cookie refresh |
| `storage_state_path` | `str` | `None` | Load Playwright `storage_state` cookies/localStorage |
| `auto_storage_state` | `bool` | `True` | Auto-load `HTML2OBSIDIAN_STORAGE_STATE`, `./auth-state.json`, `./.auth-state.json`, or `./.html2obsidian/auth-state.json` |
| `save_storage_state_path` | `str` | `None` | Save Playwright `storage_state` after fetch |
| `auth_wait_seconds` | `float` | `0.0` | Keep headed browser open before snapshot/save for manual login |
| `capture_network` | `bool` | `False` | Capture XHR/fetch requests |
| `wait_for_selector` | `str` | `None` | CSS selector to wait for before snapshot |
| `wait_for_timeout` | `float` | `10.0` | Max seconds to wait for selector |
| `summarize` | `bool` | `False` | Run LLM pre-summarisation |
| `summarizer_provider` | `str` | `"ollama"` | `"ollama"` or `"openai"` |
| `summarizer_model` | `str` | `"llama3.2:3b"` | Model name |
| `max_summary_words` | `int` | `300` | Word limit for summary |

---

## LLM Summarisation

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

## Error Behavior

On failure all functions return:

```python
{
    "success": False,
    "error": "...",
    # other fields are empty/None placeholders
}
```

Common failure causes: fetch error, invalid `llm_config` types, unsupported `site_map_style`, rejected edits.
