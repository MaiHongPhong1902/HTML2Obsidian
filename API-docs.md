# API Docs

Standalone reference for the public Python API and LLM tool-calling surface exported by this repository.

## Public Exports

The package exports these public objects from `tools`:

```python
from tools import create_obsidian_note, TOOL_SCHEMA, ObsidianNote
```

- `create_obsidian_note`: main function for fetching a URL and generating note output.
- `TOOL_SCHEMA`: JSON schema for OpenAI / Anthropic / Ollama function calling.
- `ObsidianNote`: rendered note object used internally by the formatter.

## Main Function

```python
def create_obsidian_note(
    url: str,
    vault_path: str = "",
    note_title: str = "",
    render_js: bool = True,
    extra_tags: list[str] | None = None,
    from_url: str = "",
    from_title: str = "",
    browser_profile: str | None = None,
    split_sections: bool = False,
    include_site_map: bool = False,
    site_map_style: str = "tree",
    site_map_max_depth: int = 3,
    site_map_max_internal_links: int = 120,
    site_map_max_external_links: int = 30,
    llm_config: dict | None = None,
) -> dict
```

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Source page URL. Must be `http` or `https`. |
| `vault_path` | `str` | `""` | Save output into an Obsidian vault. Empty means return strings only. |
| `note_title` | `str` | `""` | Optional custom title. If empty, title is inferred from page metadata. |
| `render_js` | `bool` | `True` | Use Playwright to render JS-heavy pages before extraction. |
| `extra_tags` | `list[str]` | `[]` | Extra tags appended after auto-tag generation. |
| `from_url` | `str` | `""` | Source URL for backlink context. |
| `from_title` | `str` | `""` | Source page title used with `from_url`. |
| `browser_profile` | `str \| None` | `None` | Existing browser profile for authenticated pages. |
| `split_sections` | `bool` | `False` | Generate one note per layout section plus an index note. |
| `include_site_map` | `bool` | `False` | Generate a dedicated site map note. |
| `site_map_style` | `str` | `"tree"` | One of `tree`, `table`, or `both`. |
| `site_map_max_depth` | `int` | `3` | Max path depth for hierarchical site map rendering. |
| `site_map_max_internal_links` | `int` | `120` | Max internal links captured into the site map. |
| `site_map_max_external_links` | `int` | `30` | Max external links captured into the site map. |
| `llm_config` | `dict \| None` | `None` | LLM-safe structured output and constrained edit controls. |

## Return Payload

```python
{
    "success": bool,
    "title": str,
    "content": str,
    "agent_context": str,
    "site_map": str,
    "structured_data": dict | None,
    "applied_llm_config": dict,
    "path": str,
    "site_map_path": str,
    "paths": list[str],
    "url": str,
    "tags": list[str],
    "entities": list[str],
    "error": str | None,
}
```

### Field Notes

- `content`: main rendered Markdown note.
- `agent_context`: compact, agent-oriented snapshot for downstream LLM use.
- `site_map`: full site-map note content when `include_site_map=True`.
- `structured_data`: normalized data snapshot for read-oriented LLM flows.
- `applied_llm_config`: tells you which requested edits were accepted or rejected.
- `path`: saved note path or split-note folder path.
- `site_map_path`: saved site-map file path when applicable.
- `paths`: list of saved split-note files. Usually empty outside `split_sections=True`.

## LLM Config

`llm_config` is designed for tool-calling scenarios where the model must inspect source data and request constrained note changes.

### Supported Shape

```python
llm_config = {
    "user_approved_edits": False,
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

| Key | Type | Default | Notes |
|---|---|---|---|
| `user_approved_edits` | `bool` | `False` | Must be `True` before any `llm_config.edit` changes are applied. |
| `include_structured_data` | `bool` | `False` | Return structured source data for the LLM to inspect. |
| `structured_data_limit` | `int` | `10` | Per-list item cap for structured output. Clamped to `1..20`. |
| `edit` | `dict` | `{}` | Safe edits applied only when `user_approved_edits=True`. |

### Edit Controls

| Key | Type | Description |
|---|---|---|
| `edit.title` | `str` | Replace the note title. Sanitized by tool rules. |
| `edit.add_tags` | `list[str]` | Add tags after auto-tag generation. |
| `edit.remove_tags` | `list[str]` | Remove matching tags from final output. |
| `edit.frontmatter_fields` | `dict` | Add non-protected frontmatter fields. |
| `edit.include_sections` | `list[str]` | Keep only the listed top-level sections. |
| `edit.exclude_sections` | `list[str]` | Remove the listed top-level sections. |

### Editable Section Keys

- `summary`
- `agent_snapshot`
- `page_structure`
- `interactive_elements`
- `content`
- `relationships`
- `references`
- `navigation`

### Protected Frontmatter Fields

These fields are tool-managed and cannot be overwritten through `llm_config.edit.frontmatter_fields`:

- `title`
- `url`
- `domain`
- `fetched`
- `tags`
- `entities`
- `from_url`
- `framework`
- `has_shadow_dom`
- `video_id`
- `channel`
- `upload_date`
- `duration`
- `map_for`
- `last_updated`
- `source_page`
- `map_style`
- `tree_depth`
- `internal_links_count`
- `external_links_count`

## Structured Data Shape

When `llm_config.include_structured_data=True`, the result contains:

```python
{
    "page": {...},
    "frontmatter": {...} | None,
    "summary": str,
    "content_excerpt": str,
    "metadata": {...},
    "layout": {...},
    "links": {...},
    "interactives": {...},
    "tool_rules": {...},
}
```

### Important Sub-Objects

- `page`: URL, status code, render mode, fetch error.
- `metadata`: title, description, canonical URL, language, author, keywords.
- `layout`: framework, shadow DOM flag, section summaries.
- `links`: internal/external link previews and counts.
- `interactives`: buttons, inputs, forms, nav links.
- `tool_rules`: editable section keys, protected fields, and edit-permission requirement.

## Split-Section Behavior

When `split_sections=True`:

- `content` returns the generated index note.
- `paths` contains all saved split-note files if `vault_path` is set.
- `llm_config.edit.title` is used for the generated title.
- Other `llm_config.edit` operations are rejected because split output is tool-generated per section.
- `structured_data` still works when requested.

## Site Map Behavior

When `include_site_map=True`:

- `site_map` contains the dedicated site-map note content.
- `site_map_path` contains the saved path if output is written to a vault.
- `site_map_style` accepts `tree`, `table`, or `both`.

## Tool-Calling Examples

### Read-Only LLM Call

```python
from tools import create_obsidian_note

result = create_obsidian_note(
    url="https://example.com",
    render_js=False,
    llm_config={
        "include_structured_data": True,
        "structured_data_limit": 5,
    },
)

print(result["structured_data"])
print(result["applied_llm_config"])
```

### User-Approved LLM Edit

```python
from tools import create_obsidian_note

result = create_obsidian_note(
    url="https://example.com",
    render_js=False,
    llm_config={
        "user_approved_edits": True,
        "include_structured_data": True,
        "edit": {
            "title": "Example Agent Note",
            "add_tags": ["llm-ready"],
            "frontmatter_fields": {"status": "reviewed"},
            "include_sections": ["agent_snapshot", "content"],
        },
    },
)

print(result["title"])
print(result["content"])
print(result["applied_llm_config"])
```

### OpenAI Tool Calling

```python
import json
import openai
from tools import TOOL_SCHEMA, create_obsidian_note

client = openai.OpenAI()

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": "Read https://example.com and return structured data only.",
        }
    ],
    tools=[{"type": "function", "function": TOOL_SCHEMA}],
)

args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
result = create_obsidian_note(**args)
```

## Rule Summary

- Read access via `structured_data` does not require edit approval.
- Any `llm_config.edit` change requires `user_approved_edits=True`.
- Protected frontmatter fields cannot be overwritten.
- Invalid tags, invalid section keys, and blocked fields are reported in `applied_llm_config["rejected"]`.
- The tool may sanitize titles, tags, and frontmatter values before applying them.

## Error Behavior

Common failure modes:

- Invalid `llm_config` type or invalid nested types.
- Unsupported `site_map_style`.
- Fetch failure for the source URL.
- Rejected edits due to missing user approval or protected fields.

On failure, the result uses:

```python
{
    "success": False,
    "error": "...",
}
```

while still returning empty placeholders for the main response fields.