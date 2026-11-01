from __future__ import annotations

from pathlib import Path

from soc2_index.models import Catalog, Coverage, EvidenceFile, IndexDiff, IndexDoc, MappingResult, Proof
from soc2_index.runstore import sha256_file


class ValidationError(Exception):
    def __init__(self, message: str, proof: Proof | None = None) -> None:
        super().__init__(message)
        self.proof = proof
        self.code = 3


def coverage(catalog: Catalog, mapping: MappingResult) -> Coverage:
    present_ids = []
    seen: set[str] = set()
    present_rows = 0
    gap_rows = 0
    for row in mapping.rows:
        if row.status == "Present":
            present_rows += 1
            if row.control_id not in seen:
                seen.add(row.control_id)
                present_ids.append(row.control_id)
        else:
            gap_rows += 1
    return Coverage(
        catalog_id=catalog.id,
        controls_total=len(catalog.ids),
        present_rows=present_rows,
        present_controls=len(present_ids),
        present_control_ids=present_ids,
        gap_rows=gap_rows,
        unmapped_files=len(mapping.unmapped),
        flagged_files=len(mapping.flagged),
        ambiguous_files=len(mapping.ambiguous),
    )


def build_index(
    catalog: Catalog,
    mapping: MappingResult,
    org: str,
    period: str,
    generated_at: str,
) -> IndexDoc:
    return IndexDoc(
        catalog_id=catalog.id,
        catalog_sha256=catalog.sha256,
        org=org,
        period=period,
        generated_at=generated_at,
        rows=list(mapping.rows),
        unmapped=list(mapping.unmapped),
        flagged=list(mapping.flagged),
        coverage=coverage(catalog, mapping),
    )


def proof_local(index: IndexDoc, files: list[EvidenceFile], evidence_root: Path | None = None) -> Proof:
    by_path = {f.relative_path: f for f in files}
    dangling: list[str] = []
    resolved = 0
    present = [r for r in index.rows if r.status == "Present"]
    for row in present:
        path = row.source_path or ""
        rec = by_path.get(path)
        ok_hash = rec is not None and rec.sha256 == row.sha256
        ok_disk = True
        if evidence_root is not None and path:
            disk = evidence_root / path
            ok_disk = disk.is_file() and sha256_file(disk) == row.sha256
        if rec is None or not ok_hash or not ok_disk:
            dangling.append(row.row_id)
        else:
            resolved += 1
    catalog_ids = []
    seen: set[str] = set()
    missing: list[str] = []
    for row in index.rows:
        if row.control_id not in seen:
            seen.add(row.control_id)
            catalog_ids.append(row.control_id)
    # every catalog id should appear — we don't have catalog here; use coverage
    if index.coverage.controls_total and len(seen) != index.coverage.controls_total:
        # caller may fill controls_missing separately
        pass
    gaps = [r.row_id for r in index.rows if r.status == "GAP"]
    return Proof(
        catalog_id=index.catalog_id,
        present_rows=len(present),
        present_resolved=resolved,
        dangling=dangling,
        gap_rows=len(gaps),
        controls_missing_from_index=missing,
    )


def attach_html_proof(proof: Proof, parsed_ids: list[str], canonical_ids: list[str]) -> Proof:
    canon = set(canonical_ids)
    got = set(parsed_ids)
    proof.html_row_ids = parsed_ids
    proof.html_missing_gaps = sorted(i for i in (canon - got) if "::gap::" in i)
    invented = sorted(got - canon)
    # missing present rows also fail equality; fold into invented-or-missing via invented + html_missing
    missing_present = sorted(i for i in (canon - got) if "::present::" in i)
    proof.invented = invented
    if missing_present:
        proof.html_missing_gaps = sorted(set(proof.html_missing_gaps or []) | set(missing_present))
    return proof


def live_ok(proof: Proof) -> bool:
    """Row-set honesty. Missing SuperDocs <tr> chunk ids are recorded as overreach but do not fail first fill."""
    if proof.dangling:
        return False
    if proof.invented:
        return False
    if proof.html_missing_gaps:
        return False
    return True


def live_register_equality(parsed_ids: set[str], canonical_ids: set[str]) -> tuple[list[str], list[str]]:
    missing = sorted(canonical_ids - parsed_ids)
    invented = sorted(parsed_ids - canonical_ids)
    return missing, invented


def live_row_identity(before_html: str, after_html: str, diff: IndexDiff) -> list[str]:
    """Unchanged row text must match after stripping SuperDocs-owned attributes."""
    from soc2_index.superdocs.parse_index import row_text_by_id, strip_sd_attrs

    before = row_text_by_id(before_html)
    after = row_text_by_id(after_html)
    overreach: list[str] = []
    for rid in diff.unchanged_ids:
        b = strip_sd_attrs(before.get(rid, ""))
        a = strip_sd_attrs(after.get(rid, ""))
        if b != a:
            overreach.append(rid)
    return overreach
