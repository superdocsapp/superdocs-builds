from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from .models import Violation
from .superdocs_client import SuperDocsClient
from .template import build_plan_template_html


def main() -> None:
    api_key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "SUPERDOCS_API_KEY is missing. Set SUPERDOCS_API_KEY in the environment and rerun."
        )

    sample_path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "violations.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    violations = tuple(Violation(**violation) for violation in sample["violations"])
    inspection_date = date.fromisoformat(sample["inspection_date"])
    document_html = build_plan_template_html(
        restaurant=sample["restaurant"],
        inspection_date=inspection_date,
        health_department=sample["health_department"],
        violations=violations,
    )
    message = (
        "Fill each violation section separately. For every cited code, write only that code's "
        "corrective action, responsible party, target date, and evidence in its existing section. "
        "Do not merge cited violations into one paragraph and do not add uncited violation codes."
    )
    session_id = f"restaurant-corrective-plan-{uuid4()}"
    client = SuperDocsClient(api_key=api_key)
    approved = client.draft_with_approval(
        document_html=document_html,
        message=message,
        session_id=session_id,
        poll_interval_seconds=5,
        max_polls=72,
        max_elapsed_seconds=360,
    )
    exported = client.export(session_id=approved.session_id, fmt="docx")
    out_dir = Path(__file__).resolve().parents[2] / "out"
    out_dir.mkdir(exist_ok=True)
    output_path = out_dir / "restaurant-corrective-plan.docx"
    output_path.write_bytes(exported)
    print(
        f"approved {len(approved.changes)} change(s), exported {output_path} "
        f"({len(exported)} bytes)"
    )


if __name__ == "__main__":
    main()

