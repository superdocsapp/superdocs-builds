from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import yaml

from soc2_index.identity import gap_row, present_row
from soc2_index.models import (
    AmbiguousItem,
    Catalog,
    EvidenceFile,
    FlaggedFile,
    IndexRow,
    MappingResult,
    UnmappedFile,
)
from soc2_index.paths import mapping_rules_path

log = logging.getLogger("soc2_index.map")


def load_rules(path: Path | None = None) -> dict:
    return yaml.safe_load((path or mapping_rules_path()).read_text(encoding="utf-8"))


def _filename_hits(rel: str, contains: list[str]) -> bool:
    name = Path(rel).name
    blob = f"{rel} {name}"
    return any(token in blob for token in contains)


def apply(
    catalog: Catalog,
    files: list[EvidenceFile],
    rules: dict | None = None,
    warnings: list[str] | None = None,
) -> MappingResult:
    rules = rules or load_rules()
    warn = warnings if warnings is not None else []
    catalog_ids = set(catalog.ids)
    present: dict[str, IndexRow] = {}
    flagged: list[FlaggedFile] = []
    unmapped: list[UnmappedFile] = []
    ambiguous: list[AmbiguousItem] = []
    mapped_paths: set[str] = set()

    rule_list = list(rules.get("rules") or [])

    def in_catalog(ids: list[str]) -> set[str]:
        extra = [i for i in ids if i not in catalog_ids]
        for i in extra:
            msg = f"control {i} not in catalog {catalog.id}; ignored"
            warn.append(msg)
            log.debug(msg)
        return set(ids) & catalog_ids

    for f in files:
        if f.injection_flags:
            flagged.append(
                FlaggedFile(
                    relative_path=f.relative_path,
                    sha256=f.sha256,
                    injection_flags=list(f.injection_flags),
                )
            )
            continue

        emitted_for_file = False

        if f.front_matter_has_controls_key:
            hits = in_catalog(list(f.front_matter_controls))
            if not hits:
                unmapped.append(
                    UnmappedFile(
                        relative_path=f.relative_path,
                        sha256=f.sha256,
                        title=f.title,
                        reason="controls_not_in_catalog",
                    )
                )
                continue
            for cid in catalog.ids:
                if cid not in hits:
                    continue
                row = present_row(
                    control_id=cid,
                    criterion=catalog.name_of(cid),
                    file_title=f.title,
                    date=f.date,
                    owner=f.owner,
                    source_path=f.relative_path,
                    sha256=f.sha256,
                    evidence_type=f.evidence_type,
                )
                present[row.row_id] = row
                emitted_for_file = True
            if emitted_for_file:
                mapped_paths.add(f.relative_path)
            continue

        non_multi: list[tuple[str, frozenset[str], str | None]] = []
        multi_ids: set[str] = set()
        multi_type: str | None = None
        for rule in rule_list:
            match = rule.get("match") or {}
            contains = list(match.get("filename_contains") or [])
            if not contains or not _filename_hits(f.relative_path, contains):
                continue
            maps = in_catalog(list(rule.get("maps_to") or []))
            if not maps:
                continue
            etype = rule.get("evidence_type")
            if rule.get("multi"):
                multi_ids |= maps
                multi_type = etype or multi_type
            else:
                non_multi.append((rule["id"], frozenset(maps), etype))

        if len(non_multi) >= 2:
            sets = {s for _, s, _ in non_multi}
            if len(sets) >= 2:
                rule_ids = [rid for rid, _, _ in non_multi]
                maps_sets = [sorted(s) for _, s, _ in non_multi]
                blob = f"{f.relative_path}::{','.join(sorted(rule_ids))}"
                digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
                ambiguous.append(
                    AmbiguousItem(
                        mapping_id=f"amb::{f.relative_path}::{digest}",
                        relative_path=f.relative_path,
                        sha256=f.sha256,
                        rule_ids=rule_ids,
                        maps_to_sets=maps_sets,
                        reason="conflicting_non_multi_rules",
                    )
                )
                continue

        control_hits: set[str] = set(multi_ids)
        etype = multi_type
        for _, s, t in non_multi:
            control_hits |= set(s)
            etype = t or etype

        if not control_hits:
            unmapped.append(
                UnmappedFile(
                    relative_path=f.relative_path,
                    sha256=f.sha256,
                    title=f.title,
                    reason="no_rule",
                )
            )
            continue

        for cid in catalog.ids:
            if cid not in control_hits:
                continue
            row = present_row(
                control_id=cid,
                criterion=catalog.name_of(cid),
                file_title=f.title,
                date=f.date,
                owner=f.owner,
                source_path=f.relative_path,
                sha256=f.sha256,
                evidence_type=etype,
            )
            present[row.row_id] = row
            emitted_for_file = True
        if emitted_for_file:
            mapped_paths.add(f.relative_path)

    rows: list[IndexRow] = []
    present_by_control: dict[str, list[IndexRow]] = {cid: [] for cid in catalog.ids}
    for row in present.values():
        present_by_control.setdefault(row.control_id, []).append(row)

    for cid in catalog.ids:
        got = present_by_control.get(cid) or []
        if got:
            got.sort(key=lambda r: r.source_path or "")
            rows.extend(got)
        else:
            rows.append(gap_row(control_id=cid, criterion=catalog.name_of(cid)))

    return MappingResult(rows=rows, unmapped=unmapped, flagged=flagged, ambiguous=ambiguous)
