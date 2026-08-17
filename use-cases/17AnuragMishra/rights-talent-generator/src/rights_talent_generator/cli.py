from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .generator import draft_offline, draft_with_superdocs, load_terms


def main() -> None:
    parser = argparse.ArgumentParser(prog="rights-talent-generator")
    parser.add_argument("--terms", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--out", required=True, help="Markdown output path")
    parser.add_argument("--docx-out", help="DOCX output path (live mode only)")
    parser.add_argument("--live-superdocs", action="store_true")
    parser.add_argument(
        "--approve-all",
        action="store_true",
        help="Explicitly approve every proposed live change; otherwise prompt per item.",
    )
    args = parser.parse_args()

    terms = load_terms(args.terms)
    template_path = Path(args.template)

    def approve(change: dict[str, Any]) -> bool:
        if args.approve_all:
            return True
        explanation = change.get("ai_explanation") or change.get("operation") or "proposed edit"
        answer = input(f"Approve {change.get('change_id')}: {explanation}? [y/N] ")
        return answer.strip().lower() in {"y", "yes"}

    if args.live_superdocs:
        result = draft_with_superdocs(terms, template_path, approve=approve)
    else:
        result = draft_offline(terms, template_path.read_text(encoding="utf-8"))
    Path(args.out).write_text(result.markdown, encoding="utf-8")
    docx_out = None
    if result.exported_docx is not None:
        docx_out = Path(args.docx_out or Path(args.out).with_suffix(".docx"))
        docx_out.write_bytes(result.exported_docx)
    if not result.is_complete:
        missing = [name for name, passed in result.clause_checks.items() if not passed]
        raise SystemExit(f"Generated agreement failed clause checks: {', '.join(missing)}")
    print(
        json.dumps(
            {
                "markdown_out": args.out,
                "docx_out": str(docx_out) if docx_out else None,
                "session_id": result.session_id,
                "reviewed_changes": result.reviewed_changes,
                "clause_checks": result.clause_checks,
                "complete": result.is_complete,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
