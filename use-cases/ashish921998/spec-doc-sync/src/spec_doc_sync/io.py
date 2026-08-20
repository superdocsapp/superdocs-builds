from __future__ import annotations

import json
from pathlib import Path

from .models import EditProposal, Plan, SpecChange


def save_plan(plan: Plan, path: Path) -> None:
    path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")


def load_plan(path: Path) -> Plan:
    value = json.loads(path.read_text(encoding="utf-8"))
    return Plan(
        previous_spec_sha256=value["previous_spec_sha256"], current_spec_sha256=value["current_spec_sha256"],
        docs_sha256=value["docs_sha256"], preview=value["preview"],
        proposals=[EditProposal(**item) for item in value.get("proposals", [])],
        changes=[SpecChange(**item) for item in value.get("changes", [])], stop_reason=value.get("stop_reason"),
    )

