"""
Runnable end-to-end: scans a git repo for changed Python files, checks a target markdown doc for stale
references, and (once you approve) applies scoped updates via the real SuperDocs API.

Usage:
    python -m src.cli check /path/to/repo README.md
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.client import SuperDocsClient
from src.code_diff import diff_functions
from src.doc_index import parse_markdown_chunks
from src.git_integration import get_changed_python_files
from src.sync_engine import build_proposals, apply_approved_updates


def check(repo_path: str, doc_path: str, report_only: bool = False):
    changed_files = get_changed_python_files(repo_path)
    if not changed_files:
        print("No changed Python files since HEAD. Nothing to check.")
        return

    all_changes = []
    for cf in changed_files:
        try:
            all_changes.extend(diff_functions(cf.old_content, cf.new_content, file_path=cf.path))
        except SyntaxError as e:
            print(f"  skipping {cf.path}: does not parse as valid Python ({e})")

    if not all_changes:
        print("Changed files found, but no function-level changes detected (docstring/body-only edits "
              "or non-function changes). Nothing to propose.")
        return

    doc_text = Path(doc_path).read_text(encoding="utf-8")
    doc_chunks = parse_markdown_chunks(doc_text)

    proposals = build_proposals(all_changes, doc_chunks)
    if not proposals:
        print("Code changed, but nothing that affects documented functions. Docs are still accurate.")
        return

    print(f"\n{len(proposals)} proposal(s):\n")
    for i, p in enumerate(proposals):
        print(f"  [{i}] {p.summary()}")

    actionable = [p for p in proposals if p.kind != "flag_undocumented"]
    if not actionable:
        print("\nAll proposals are undocumented-function flags -- nothing to apply automatically. "
              "Consider adding documentation for these manually.")
        return

    print(f"\n{len(actionable)} actionable proposal(s) can be applied via SuperDocs.")

    if report_only:
        # Used by the VS Code extension, which runs this as a non-interactive subprocess -- calling
        # input() here would hang forever waiting for a TTY that doesn't exist. The extension shows these
        # proposals read-only and points the user at the interactive CLI to actually apply them.
        print("(report-only mode: nothing applied. Run without --report-only in a terminal to apply.)")
        return

    answer = input("Apply ALL actionable proposals now? This will spend SuperDocs operations. [y/N] ")
    if answer.strip().lower() != "y":
        print("Skipped. Nothing applied.")
        return

    client = SuperDocsClient()
    session_id = f"docsync-{Path(doc_path).stem}"
    doc = client.upload_document(doc_path, session_id)

    results = apply_approved_updates(client, session_id, doc.html, actionable)
    for citation, response_text in results.items():
        print(f"  applied ({citation}): {response_text[:100]}")

    # IMPORTANT: apply_approved_updates' chat calls already updated the SERVER-SIDE session as it went (each
    # chat turn's document_html argument feeds the next turn), so unlike Build A's local-repair scenario,
    # no extra sync call is needed here before export -- export() reads the session state chat() already
    # left in place. Noted explicitly because Build A's real bug (repair happening only in local memory,
    # never reaching the server) makes this an easy thing to get wrong; DocSync's flow avoids it because
    # every edit IS a server-side chat call, not a local-only patch.
    out_bytes = client.export(session_id, fmt="markdown")
    out_path = Path(f"{Path(doc_path).stem}_synced.md")
    out_path.write_bytes(out_bytes)
    print(f"\nExported updated doc -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "check":
        print("Usage: python -m src.cli check /path/to/repo README.md [--report-only]")
        sys.exit(1)
    report_only = "--report-only" in sys.argv
    check(sys.argv[2], sys.argv[3], report_only=report_only)
