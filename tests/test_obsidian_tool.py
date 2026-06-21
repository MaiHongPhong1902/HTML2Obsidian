"""Unit tests for obsidian_tool sanitisation + LLM config validation."""

from tools import obsidian_tool as ot


# ── Filename / title sanitisation ─────────────────────────────────────────────

def test_safe_filename():
    assert ot._safe_filename('a/b:c*?"<>|') == "abc"
    assert ot._safe_filename("") == "Untitled"
    assert ot._safe_filename("...") == "Untitled"
    assert ot._safe_filename("Normal Title") == "Normal Title"


def test_sanitize_title():
    assert ot._sanitize_title("  Hello\nWorld  ") == "Hello World"
    assert ot._sanitize_title(None) == ""
    assert ot._sanitize_title('bad:/\\*?"<>|chars') == "badchars"


def test_normalize_tag_min_length_two():
    assert ot._normalize_tag("ab") == "ab"
    assert ot._normalize_tag("a") == ""
    assert ot._normalize_tag("Hello World") == "hello-world"
    assert ot._normalize_tag("123") == ""


# ── LLM config gating ─────────────────────────────────────────────────────────

def test_llm_edit_requires_approval():
    norm = ot._normalize_llm_config({"edit": {"title": "New Title"}})
    assert norm["edit"]["title"] == ""           # cleared without approval
    assert any("approval" in r for r in norm["rejected"])


def test_llm_edit_applied_with_approval():
    norm = ot._normalize_llm_config(
        {"user_approved_edits": True, "edit": {"title": "New Title"}}
    )
    assert norm["edit"]["title"] == "New Title"


def test_llm_frontmatter_protected_field_rejected():
    norm = ot._normalize_llm_config(
        {
            "user_approved_edits": True,
            "edit": {"frontmatter_fields": {"url": "evil", "custom": "ok"}},
        }
    )
    assert norm["edit"]["frontmatter_fields"] == {"custom": "ok"}
    assert any("url" in r and "protected" in r for r in norm["rejected"])


def test_structured_data_limit_clamped():
    norm = ot._normalize_llm_config({"structured_data_limit": 9999})
    assert norm["structured_data_limit"] == ot.MAX_LLM_STRUCTURED_ITEMS
    norm2 = ot._normalize_llm_config({"structured_data_limit": "oops"})
    assert norm2["structured_data_limit"] == 10


# ── Section filtering ─────────────────────────────────────────────────────────

def _sample_body() -> str:
    return (
        "# Title\n\n"
        "## 📝 Summary\n\nsummary text\n\n"
        "## 📄 Content\n\ncontent text\n"
    )


def test_filter_note_sections_include_only():
    out = ot._filter_note_sections(_sample_body(), include_sections=["summary"], exclude_sections=[])
    assert "📝 Summary" in out
    assert "📄 Content" not in out


def test_filter_note_sections_exclude():
    out = ot._filter_note_sections(_sample_body(), include_sections=[], exclude_sections=["content"])
    assert "📝 Summary" in out
    assert "📄 Content" not in out


def test_filter_note_sections_keeps_title():
    out = ot._filter_note_sections(_sample_body(), include_sections=["summary"], exclude_sections=[])
    assert out.startswith("# Title")
