"""
tools — Browser → Obsidian Note package.

Usage:
    from tools import create_obsidian_note, TOOL_SCHEMA
    result = create_obsidian_note(url="https://example.com", vault_path="./vault")
"""

from .obsidian_tool import create_obsidian_note, TOOL_SCHEMA
from .obsidian_formatter import ObsidianNote

__all__ = [
    "create_obsidian_note",
    "TOOL_SCHEMA",
    "ObsidianNote",
]
