from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .models import EditProposal, Plan


def replace_exact(text: str, needle: str, replacement: str) -> tuple[str, int]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])")
    return pattern.subn(replacement, text)


def apply_plan(plan: Plan, docs_dir: Path, state_path: Path) -> dict:
    changed: list[str] = []
    proof: dict[str, dict] = {}
    before = {str(path.relative_to(docs_dir)): hashlib.sha256(path.read_bytes()).hexdigest() for path in docs_dir.rglob("*.md")}
    for proposal in plan.proposals:
        if proposal.decision != "approved" or not proposal.file:
            continue
        path = docs_dir / proposal.file
        text = path.read_text(encoding="utf-8")
        if proposal.operation == "replace_all":
            assert proposal.needle and proposal.replacement
            updated, count = replace_exact(text, proposal.needle, proposal.replacement)
            if count != proposal.occurrences:
                raise RuntimeError(f"stale plan for {proposal.file}: expected {proposal.occurrences} matches, found {count}")
        elif proposal.operation == "append_section":
            assert proposal.replacement
            updated = text + proposal.replacement
        elif proposal.operation == "mark_deprecated":
            assert proposal.needle
            updated, count = replace_exact(text, proposal.needle, f"{proposal.needle} (deprecated)")
            if count != proposal.occurrences:
                raise RuntimeError(f"stale plan for {proposal.file}: expected {proposal.occurrences} matches, found {count}")
        else:
            continue
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(proposal.file)

    after = {str(path.relative_to(docs_dir)): hashlib.sha256(path.read_bytes()).hexdigest() for path in docs_dir.rglob("*.md")}
    for name, checksum in before.items():
        proof[name] = {"before": checksum, "after": after[name], "byte_identical": checksum == after[name]}
    state = {
        "previous_spec_sha256": plan.previous_spec_sha256,
        "current_spec_sha256": plan.current_spec_sha256,
        "changed_files": sorted(set(changed)),
        "proof": proof,
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state

