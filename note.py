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
                             'Shortcuts: chrome, edge, firefox; supports chrome:Default, edge:Profile 1, or an absolute path.')
    parser.add_argument("--browser-channel", default="", metavar="CHANNEL",
                        help="Playwright browser channel to launch, e.g. chrome, msedge, chromium")
    parser.add_argument("--headed", action="store_true",
                        help="Open a visible browser window so cookies/login can be refreshed")
    parser.add_argument("--cookies", "--storage-state", dest="storage_state", default="", metavar="FILE",
                        help="Load cookies/localStorage from a Playwright storage_state JSON file")
    parser.add_argument("--no-auto-cookies", action="store_true",
                        help="Disable automatic loading from saved auth-state.json storage files")
    parser.add_argument("--save-cookies", "--save-storage-state", dest="save_storage_state", default="", metavar="FILE",
                        help="Save cookies/localStorage to a Playwright storage_state JSON file after fetch")
    parser.add_argument("--auth-wait", type=float, default=0.0, metavar="SECONDS",
                        help="Keep headed browser open before snapshot/save so you can finish login")
    parser.add_argument("--split", action="store_true",
                        help="Split note into sub-notes by page section (saved in vault/{Title}/ subfolder)")
    parser.add_argument("--site-map", "--sitemap", dest="site_map", action="store_true",
                        help="Generate a dedicated site map note with hierarchical URL tree output")
    parser.add_argument("--site-map-style", default="tree", metavar="STYLE",
                        choices=["tree", "table", "both"],
                        help="Site map rendering style: tree, table, or both (default: tree)")
    parser.add_argument("--site-map-depth", type=int, default=3, metavar="N",
                        help="Maximum URL depth to expand in the site map tree (default: 3)")
    parser.add_argument("--site-map-links", type=int, default=120, metavar="N",
                        help="Maximum internal links to include in the site map (default: 120)")
    parser.add_argument("--site-map-external-links", type=int, default=30, metavar="N",
                        help="Maximum external links to include in the site map (default: 30)")
    parser.add_argument("url", help="URL to fetch")

    args = parser.parse_args()

    result = create_obsidian_note(
        url=args.url,
        vault_path=args.vault,
        note_title=args.title,
        render_js=not args.no_js,
        extra_tags=args.tags,
        browser_profile=args.profile or None,
        browser_channel=args.browser_channel or None,
        browser_headless=not args.headed,
        storage_state_path=args.storage_state,
        auto_storage_state=not args.no_auto_cookies,
        save_storage_state_path=args.save_storage_state,
        auth_wait_seconds=args.auth_wait,
        split_sections=args.split,
        include_site_map=args.site_map,
        site_map_style=args.site_map_style,
        site_map_max_depth=args.site_map_depth,
        site_map_max_internal_links=args.site_map_links,
        site_map_max_external_links=args.site_map_external_links,
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
        if result.get("site_map_path"):
            print(f"Site map: {result['site_map_path']}")
        print(f"Tags:  {', '.join(result['tags'])}")
        if result.get("entities"):
            print(f"Entities: {', '.join(result['entities'][:8])}")
    else:
        print(result["content"])
        if result.get("site_map"):
            print("\n\n--- SITE MAP ---\n")
            print(result["site_map"])


if __name__ == "__main__":
    main()
