"""Unit tests for ObsidianNote / ObsidianFormatter pure helpers."""

import yaml

from tools.obsidian_formatter import ObsidianFormatter, ObsidianNote, SiteMapConfig


# ── ObsidianNote YAML rendering ───────────────────────────────────────────────

def test_yaml_scalar_quotes_special_strings():
    assert ObsidianNote._yaml_scalar("plain") == "plain"
    assert ObsidianNote._yaml_scalar("has: colon") == '"has: colon"'
    assert ObsidianNote._yaml_scalar('say "hi"') == '"say \\"hi\\""'
    assert ObsidianNote._yaml_scalar("- leading dash") == '"- leading dash"'
    assert ObsidianNote._yaml_scalar("true") == '"true"'
    assert ObsidianNote._yaml_scalar("") == '""'


def test_yaml_scalar_types():
    assert ObsidianNote._yaml_scalar(True) == "true"
    assert ObsidianNote._yaml_scalar(False) == "false"
    assert ObsidianNote._yaml_scalar(7) == "7"
    assert ObsidianNote._yaml_scalar(None) == '""'


def test_yaml_scalar_quotes_numeric_strings():
    # Numeric-looking strings must stay strings, not be parsed as numbers.
    assert ObsidianNote._yaml_scalar("1.0") == '"1.0"'
    assert ObsidianNote._yaml_scalar("007") == '"007"'
    assert ObsidianNote._yaml_scalar("-42") == '"-42"'
    note = ObsidianNote(frontmatter={"version": "1.0", "code": "007"}, body="x")
    parsed = yaml.safe_load(note.render().split("---", 2)[1])
    assert parsed["version"] == "1.0"
    assert parsed["code"] == "007"


def test_render_roundtrips_through_yaml():
    note = ObsidianNote(
        frontmatter={
            "title": 'C++: a "great" lang',
            "tags": ["- weird", "c:plus", "ok", "true"],
            "count": 3,
            "flag": True,
            "empty": [],
            "url": "https://example.com/x?a=1",
        },
        body="hello body",
    )
    rendered = note.render()
    front = rendered.split("---", 2)[1]
    parsed = yaml.safe_load(front)

    assert parsed["title"] == 'C++: a "great" lang'
    assert parsed["tags"] == ["- weird", "c:plus", "ok", "true"]
    assert parsed["count"] == 3
    assert parsed["flag"] is True
    assert parsed["empty"] == []
    assert parsed["url"] == "https://example.com/x?a=1"
    assert rendered.endswith("hello body")


# ── Tag normalisation ─────────────────────────────────────────────────────────

def test_normalize_tag():
    fmt = ObsidianFormatter(use_spacy=False)
    assert fmt._normalize_tag("Hello World") == "hello-world"
    assert fmt._normalize_tag("R&D") == "r-and-d"
    assert fmt._normalize_tag("www") == ""          # blacklisted
    assert fmt._normalize_tag("ab") == ""           # too short (<3)
    assert fmt._normalize_tag("123") == ""          # pure digits


def test_append_tag_dedupes():
    fmt = ObsidianFormatter(use_spacy=False)
    tags: list[str] = []
    fmt._append_tag(tags, "Python")
    fmt._append_tag(tags, "python")
    fmt._append_tag(tags, "www")
    assert tags == ["python"]


# ── Noise detection ───────────────────────────────────────────────────────────

def test_is_noise():
    fmt = ObsidianFormatter(use_spacy=False)
    assert fmt._is_noise("log in") is True
    assert fmt._is_noise("the") is True
    assert fmt._is_noise("42") is True
    assert fmt._is_noise("ab") is True
    assert fmt._is_noise("Knowledge Graph") is False


# ── URL tag extraction ────────────────────────────────────────────────────────

def test_extract_url_tags_github():
    fmt = ObsidianFormatter(use_spacy=False)
    tags = fmt._extract_url_tags("https://github.com/owner/myrepo", "github.com")
    assert "repository" in tags
    assert "myrepo" in tags


# ── Content outline ───────────────────────────────────────────────────────────

def test_extract_content_outline_dedupes_order():
    fmt = ObsidianFormatter(use_spacy=False)
    text = "# Alpha\nbody\n## Beta\n# Alpha\n"
    assert fmt._extract_content_outline(text) == ["Alpha", "Beta"]


# ── Wikify ────────────────────────────────────────────────────────────────────

def test_wikify_links_first_occurrence_only():
    fmt = ObsidianFormatter(use_spacy=False)
    out = fmt._wikify("Python is great. Python rocks.", ["Python"], "Doc")
    assert out.count("[[Python]]") == 1
    assert out.startswith("[[Python]] is great.")


def test_wikify_skips_protected_zones():
    fmt = ObsidianFormatter(use_spacy=False)
    out = fmt._wikify("Use `Python` then Python again.", ["Python"], "Doc")
    assert "`Python`" in out                  # code span untouched
    assert "[[Python]] again" in out          # plain occurrence linked


def test_wikify_skips_page_title():
    fmt = ObsidianFormatter(use_spacy=False)
    out = fmt._wikify("Python tutorial", ["Python"], "Python")
    assert "[[Python]]" not in out


def test_wikify_links_punctuation_entities():
    fmt = ObsidianFormatter(use_spacy=False)
    out = fmt._wikify("I write C++ and .NET and Node.js daily.", ["C++", ".NET", "Node.js"], "Doc")
    assert "[[C++]]" in out
    assert "[[.NET]]" in out
    assert "[[Node.js]]" in out


def test_wikify_word_boundary_still_respected():
    fmt = ObsidianFormatter(use_spacy=False)
    out = fmt._wikify("Pythonic code", ["Python"], "Doc")
    # "Python" inside "Pythonic" must not be linked
    assert "[[Python]]" not in out


# ── Nav url + path helpers ────────────────────────────────────────────────────

def test_normalize_nav_url_strips_fragment():
    fmt = ObsidianFormatter(use_spacy=False)
    assert fmt._normalize_nav_url("https://x.com/a#frag") == "https://x.com/a"


def test_format_path_segment():
    fmt = ObsidianFormatter(use_spacy=False)
    assert fmt._format_path_segment("hello-world_page") == "hello world page"
    assert fmt._format_path_segment("") == "root"


def test_build_internal_tree_lines():
    fmt = ObsidianFormatter(use_spacy=False)
    links = [{
        "url": "https://x.com/docs/intro",
        "note": "[[Intro]]",
        "title": "Intro",
        "type": "internal",
    }]
    lines = fmt._build_internal_tree_lines(links, max_depth=3)
    joined = "\n".join(lines)
    assert lines[0] == "- `/`"
    assert "`docs/`" in joined
    assert "[[Intro]]" in joined


# ── SiteMapConfig validation ──────────────────────────────────────────────────

def test_sitemap_config_rejects_bad_style():
    import pytest
    with pytest.raises(ValueError):
        SiteMapConfig(style="nonsense")


def test_sitemap_config_clamps_values():
    cfg = SiteMapConfig(style="tree", max_internal_links=0, max_external_links=-5, max_depth=0)
    assert cfg.max_internal_links == 1
    assert cfg.max_external_links == 0
    assert cfg.max_depth == 1
