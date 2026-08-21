from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spec_doc_sync.planner import build_plan
from spec_doc_sync.superdocs import SuperDocsClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one credentialed SuperDocs review round-trip")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    api_key = sys.stdin.read().strip()
    if not api_key.startswith("sk_"):
        raise SystemExit("expected a SuperDocs sk_ API key on standard input")

    root = Path(__file__).resolve().parents[1]
    docs = root / "fixtures" / "docs"
    plan = build_plan(root / "fixtures" / "openapi-v1.yaml", root / "fixtures" / "openapi-v2.yaml", docs)
    proposal = next(item for item in plan.proposals if item.operation == "replace_all" and item.file == "reference.md")

    decisions: list[dict[str, object]] = []

    def decide(change: dict) -> tuple[bool, str]:
        old_html = str(change.get("old_html", ""))
        new_html = str(change.get("new_html", ""))
        approved = "customer_id" in old_html and "account_id" in new_html
        decisions.append({"approved": approved, "change_id_present": bool(change.get("change_id"))})
        feedback = "" if approved else "Only rename customer_id to account_id; do not change unrelated text."
        return approved, feedback

    client = SuperDocsClient(api_key=api_key)
    result = client.propose(docs / proposal.file, proposal, decide, poll_seconds=1.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    exported = client.export(result["session_id"], args.output.name)
    args.output.write_bytes(exported)

    print(
        json.dumps(
            {
                "status": result.get("status"),
                "review_decisions": len(decisions),
                "approved": sum(bool(item["approved"]) for item in decisions),
                "rejected": sum(not bool(item["approved"]) for item in decisions),
                "export_bytes": len(exported),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

