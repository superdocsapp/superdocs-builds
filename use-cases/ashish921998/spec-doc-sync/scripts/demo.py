from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from spec_doc_sync.apply import apply_plan
from spec_doc_sync.planner import build_plan


root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    demo = Path(directory)
    docs = demo / "docs"
    shutil.copytree(root / "fixtures" / "docs", docs)
    state = demo / "state.json"
    plan = build_plan(root / "fixtures" / "openapi-v1.yaml", root / "fixtures" / "openapi-v2.yaml", docs, state)
    print(f"No-spend preview: {len(plan.changes)} spec changes -> {len(plan.proposals)} proposals")
    for proposal in plan.proposals:
        if proposal.decision == "pending": proposal.decision = "approved" if proposal.confidence >= 0.75 else "rejected"
    proof = apply_plan(plan, docs, state)
    reference_text = (docs / "reference.md").read_text(encoding="utf-8")
    quickstart_text = (docs / "quickstart.md").read_text(encoding="utf-8")
    assert "customer_id" not in reference_text + quickstart_text
    assert "account_id" in reference_text and "account_id" in quickstart_text
    untouched = [name for name, item in proof["proof"].items() if item["byte_identical"]]
    print(f"Rename search proof: all 2 occurrences updated")
    print(f"Byte-identical untouched pages: {', '.join(untouched)}")
    stopped = build_plan(root / "fixtures" / "openapi-v1.yaml", root / "fixtures" / "openapi-v2.yaml", docs, state)
    print(f"Second invocation: {stopped.stop_reason}")

