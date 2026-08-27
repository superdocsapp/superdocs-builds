from __future__ import annotations

from soc2_index.models import IndexRow


def row_id(control_id: str, status: str, evidence_key: str) -> str:
    st = status.lower()
    if st not in {"present", "gap"}:
        raise ValueError(f"bad status {status}")
    if "::" in evidence_key:
        raise ValueError("evidence_key must not contain ::")
    return f"{control_id}::{st}::{evidence_key}"


def parse_row_id(value: str) -> tuple[str, str, str] | None:
    parts = value.split("::")
    if len(parts) != 3:
        return None
    control_id, status, key = parts
    if status not in {"present", "gap"}:
        return None
    if not control_id or not key:
        return None
    return control_id, status, key


def present_row(
    *,
    control_id: str,
    criterion: str,
    file_title: str | None,
    date: str | None,
    owner: str | None,
    source_path: str,
    sha256: str,
    evidence_type: str | None,
) -> IndexRow:
    return IndexRow(
        row_id=row_id(control_id, "Present", source_path),
        control_id=control_id,
        criterion=criterion,
        status="Present",
        evidence_title=file_title,
        date=date,
        owner=owner,
        source_path=source_path,
        sha256=sha256,
        gap_reason=None,
        evidence_type=evidence_type,
    )


def gap_row(*, control_id: str, criterion: str) -> IndexRow:
    reason = (
        f"No document in the evidence set matched {control_id} ({criterion}) "
        "via front-matter, filename, or header rules."
    )
    return IndexRow(
        row_id=row_id(control_id, "GAP", "none"),
        control_id=control_id,
        criterion=criterion,
        status="GAP",
        evidence_title=None,
        date=None,
        owner=None,
        source_path=None,
        sha256=None,
        gap_reason=reason,
        evidence_type=None,
    )
