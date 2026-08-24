"""Generate local previews or run an explicit one-shot SuperDocs export."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from mock_data import load_mock_catalog
from superdocs_client import SuperDocsClient
from workflow import build_preview, export_manual_after_approved_edit, write_preview


def _load_invoker(dotted_path: str):
    module_name, separator, attribute = dotted_path.partition(":")
    if not separator:
        raise ValueError("--mcp-invoker must use module:function syntax")
    return getattr(importlib.import_module(module_name), attribute)


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 2A rental document package")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="Build local HTML/text artifacts only (no MCP calls).")
    mode.add_argument("--live", action="store_true", help="Run upload, async AI edit, explicit approval, and PDF export through a configured SuperDocs MCP invoker.")
    parser.add_argument("--property", default="green", choices=("green", "blue"))
    parser.add_argument("--language", default="en", choices=("en", "kn"))
    parser.add_argument("--output-dir", type=Path, default=Path("output") / "preview")
    parser.add_argument("--mcp-invoker", help="Configured MCP bridge in module:function form; required with --live.")
    args = parser.parse_args()
    catalog = load_mock_catalog()

    if args.preview:
        paths = write_preview(build_preview(catalog, args.property, args.language), args.output_dir)
        print("Preview completed without SuperDocs or AI operations:")
        for path in paths:
            print(path)
        return

    if not args.mcp_invoker:
        parser.error("--live requires --mcp-invoker module:function. It will not auto-approve edits.")
    result = export_manual_after_approved_edit(
        SuperDocsClient(_load_invoker(args.mcp_invoker)), catalog, args.property, args.language
    )
    print(f"Uploaded document: {result['document_id']}; session: {result['session_id']}; version: {result['version']}")
    print(f"Proposed change {result['change_id']} was '{result['status_before_approval']}' before explicit approval.")
    print(f"Approval result: {result['approved']}")
    print(f"PDF export: {result['export']}")


if __name__ == "__main__":
    main()
