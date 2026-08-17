"""Generate a manual preview or explicitly export it through SuperDocs."""

from __future__ import annotations

import argparse
from pathlib import Path

from generate_all import _load_invoker
from mock_data import load_mock_catalog
from superdocs_client import SuperDocsClient
from workflow import build_preview, export_manual_once, write_preview


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--property", default="green", choices=("green", "blue"))
    parser.add_argument("--language", default="en", choices=("en", "kn"))
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--export", choices=("pdf",))
    parser.add_argument("--mcp-invoker", help="Configured MCP bridge in module:function form.")
    args = parser.parse_args()
    catalog = load_mock_catalog()
    if args.preview:
        for path in write_preview(build_preview(catalog, args.property, args.language), Path("output") / "preview"):
            print(path)
        return
    if args.export != "pdf":
        parser.error("Choose --preview or --export pdf")
    if not args.mcp_invoker:
        parser.error("--export pdf requires --mcp-invoker module:function; edits are never auto-approved.")
    result = export_manual_once(SuperDocsClient(_load_invoker(args.mcp_invoker)), catalog, args.property, args.language)
    print(result)


if __name__ == "__main__":
    main()
