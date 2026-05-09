#!/usr/bin/env python3
"""note.py — CLI for creating Obsidian notes from URLs."""

import argparse
import io
import sys

# Force UTF-8 on Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from tools import create_obsidian_note


def main():
    parser = argparse.ArgumentParser(
        prog="note",
        description="Fetch a URL and create an Obsidian Markdown note.",
    )
    parser.add_argument("-o", "--vault", default="", metavar="DIR",
                        help="Obsidian vault directory to save the note (default: print to stdout)")
    parser.add_argument("-t", "--title", default="", metavar="TITLE",
                        help="Custom note title")
    parser.add_argument("--no-js", action="store_true",
                        help="Skip JS rendering (faster, for static pages)")
    parser.add_argument("--tags", nargs="*", default=[], metavar="TAG",
                        help="Extra tags to add")
    parser.add_argument("--profile", default="", metavar="PROFILE",
                        help='Browser profile to use for cookies/sessions. '
                             'Shortcuts: chrome, edge, firefox. Or an absolute path.')
    parser.add_argument("--split", action="store_true",
                        help="Split note into sub-notes by page section (saved in vault/{Title}/ subfolder)")
    parser.add_argument("url", help="URL to fetch")

    args = parser.parse_args()

    result = create_obsidian_note(
        url=args.url,
        vault_path=args.vault,
        note_title=args.title,
        render_js=not args.no_js,
        extra_tags=args.tags,
        browser_profile=args.profile or None,
        split_sections=args.split,
    )

    if not result["success"]:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.vault:
        if args.split:
            paths = result.get("paths", [])
            print(f"Saved {len(paths)} files in: {result['path']}")
            for p in paths:
                print(f"  {p}")
        else:
            print(f"Saved: {result['path']}")
        print(f"Tags:  {', '.join(result['tags'])}")
        if result.get("entities"):
            print(f"Entities: {', '.join(result['entities'][:8])}")
    else:
        print(result["content"])


if __name__ == "__main__":
    main()
