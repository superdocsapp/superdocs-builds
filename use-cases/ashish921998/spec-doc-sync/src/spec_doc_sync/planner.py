from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .diff import diff_specs, load_spec, stable_id
from .models import EditProposal, Plan, SpecChange


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docs_digest(directory: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(directory.rglob("*.md")):
        hasher.update(str(path.relative_to(directory)).encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def word_count(text: str, needle: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])", text))


def build_plan(previous_path: Path, current_path: Path, docs_dir: Path, state_path: Path | None = None) -> Plan:
    previous_sha, current_sha = digest(previous_path), digest(current_path)
    current_docs_sha = docs_digest(docs_dir)
    if state_path and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("previous_spec_sha256") == previous_sha and state.get("current_spec_sha256") == current_sha:
            return Plan(previous_sha, current_sha, current_docs_sha, True, stop_reason="specification pair already processed; own output cannot retrigger the loop")

    changes = diff_specs(load_spec(previous_path), load_spec(current_path))
    proposals: list[EditProposal] = []
    doc_files = sorted(docs_dir.rglob("*.md"))
    for change in changes:
        proposals.extend(proposals_for_change(change, docs_dir, doc_files))
    return Plan(previous_sha, current_sha, current_docs_sha, True, proposals, changes)


def proposals_for_change(change: SpecChange, docs_dir: Path, files: list[Path]) -> list[EditProposal]:
    if change.kind == "renamed" and isinstance(change.before, str) and isinstance(change.after, str):
        matches = []
        for path in files:
            count = word_count(path.read_text(encoding="utf-8"), change.before)
            if count:
                matches.append((path, count))
        if not matches:
            return [EditProposal(stable_id(change.id, "missing"), change.id, None, "escalate", change.before, change.after, 0, 0.5, "Renamed field has no exact documentation occurrence; do not guess where it belongs.", "escalated")]
        return [
            EditProposal(
                stable_id(change.id, str(path)), change.id, str(path.relative_to(docs_dir)), "replace_all",
                change.before, change.after, count, 0.99,
                f"Replace every exact `{change.before}` token in this page; search proof expects {count} occurrence(s).",
            ) for path, count in matches
        ]
    if change.confidence < 0.7:
        return [EditProposal(stable_id(change.id, "ambiguous"), change.id, None, "escalate", str(change.before), None, 0, change.confidence, change.explanation, "escalated")]

    terminal = change.location.rsplit(".", 1)[-1]
    if change.kind == "deprecated":
        matches = []
        for path in files:
            count = word_count(path.read_text(encoding="utf-8"), terminal)
            if count:
                matches.append((path, count))
        return [
            EditProposal(stable_id(change.id, str(path)), change.id, str(path.relative_to(docs_dir)), "mark_deprecated", terminal, None, count, 0.9, f"Mark references to `{terminal}` deprecated without deleting context.")
            for path, count in matches
        ] or [EditProposal(stable_id(change.id, "missing"), change.id, None, "escalate", terminal, None, 0, 0.5, "Deprecated field is undocumented; writer must select a destination.", "escalated")]

    if change.kind == "added":
        target = next((path for path in files if path.name in {"reference.md", "api.md"}), files[0] if files else None)
        if not target:
            return [EditProposal(stable_id(change.id, "no-docs"), change.id, None, "escalate", None, None, 0, 0.2, "No Markdown destination exists.", "escalated")]
        summary = change.after.get("summary") if isinstance(change.after, dict) else None
        description = change.after.get("description") if isinstance(change.after, dict) else None
        section = f"\n## {summary or terminal}\n\n{description or 'Specification added this capability; wording needs writer review.'}\n"
        return [EditProposal(stable_id(change.id, str(target)), change.id, str(target.relative_to(docs_dir)), "append_section", None, section, 0, 0.78 if description else 0.58, "Add only the new capability section; existing pages remain untouched.")]

    return [EditProposal(stable_id(change.id, "manual"), change.id, None, "escalate", terminal, None, 0, 0.45, "Change is real, but an automatic edit is not sufficiently grounded.", "escalated")]

