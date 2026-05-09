"""
tools — Browser → Obsidian Note package.

Usage:
    from tools import create_obsidian_note, TOOL_SCHEMA
    result = create_obsidian_note(url="https://example.com", vault_path="./vault")

    # Fast element queries for LLMs:
    from tools import query_page_elements, QUERY_SCHEMA
    result = query_page_elements(url="https://example.com", queries={"title": "h1", "links": "a"})
"""

from .obsidian_tool import create_obsidian_note, TOOL_SCHEMA, query_page_elements, QUERY_SCHEMA
from .obsidian_formatter import ObsidianNote

__all__ = [
    "create_obsidian_note",
    "TOOL_SCHEMA",
    "query_page_elements",
    "QUERY_SCHEMA",
    "ObsidianNote",
]
