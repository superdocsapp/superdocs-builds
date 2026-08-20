"""
CLI: generate a client update + document-checklist letter for one or all
cases in a case file, via the real SuperDocs API, and export each as .docx.

Usage:
    export SUPERDOCS_API_KEY=sk_...
    python -m case_status_desk.generate --cases data/sample_cases.json --out out/
    python -m case_status_desk.generate --cases data/sample_cases.json --case-id CASE-1001 --out out/

Requires SUPERDOCS_API_KEY. This CLI path is a local/dev convenience for
running against a flat JSON case file (see data/sample_cases.json). The
production path is the DB-backed service in service.py, used by app.py.

Note: the previous --agent-signup flow (auto-registering for a fresh
SuperDocs API key over the network, unsupervised) has been removed --
credential creation in production must be a deliberate human action, not
something a script does on your behalf.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .cases import Case, RequiredDocument, build_letter_instruction
from .superdocs_client import SuperDocsClient, SuperDocsError


def load_cases(path: Path) -> list[Case]:
    raw = json.loads(path.read_text())
    cases = []
    for item in raw:
        docs = [
            RequiredDocument(
                name=d["name"],
                form_type=d["form_type"],
                received=d.get("received", False),
                due_date=date.fromisoformat(d["due_date"]) if d.get("due_date") else None,
            )
            for d in item.get("required_documents", [])
        ]
        cases.append(
            Case(
                case_id=item["case_id"],
                client_name=item["client_name"],
                case_type=item["case_type"],
                stage=item["stage"],
                language=item.get("language", "en"),
                required_documents=docs,
            )
        )
    return cases


def generate_letter(client: SuperDocsClient, case: Case, out_dir: Path) -> Path:
    session_id = f"case-status-{case.case_id}"
    instruction = build_letter_instruction(case)
    result = client.chat(session_id=session_id, message=instruction)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case.case_id}-status-letter.docx"
    file_bytes = client.export(session_id=session_id, fmt="docx", filename=case.case_id + "-status-letter")
    out_path.write_bytes(file_bytes)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="Path to a case-file JSON (see data/sample_cases.json)")
    parser.add_argument("--case-id", help="Generate for only this case id (default: all cases)")
    parser.add_argument("--out", type=Path, default=Path("out"), help="Output directory for .docx letters")
    args = parser.parse_args(argv)

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("No SUPERDOCS_API_KEY set. Aborting.", file=sys.stderr)
        return 2

    client = SuperDocsClient(api_key=api_key)
    cases = load_cases(args.cases)
    if args.case_id:
        cases = [c for c in cases if c.case_id == args.case_id]
        if not cases:
            print(f"No case with id {args.case_id!r} in {args.cases}", file=sys.stderr)
            return 2

    for case in cases:
        try:
            path = generate_letter(client, case, args.out)
            print(f"{case.case_id}: wrote {path}")
        except SuperDocsError as e:
            print(f"{case.case_id}: FAILED -- {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
