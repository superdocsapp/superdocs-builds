from __future__ import annotations

from soc2_index.models import ChangedRow, FieldChange, IndexDiff, IndexDoc, IndexRow, Rename

_TRACKED = ("evidence_title", "date", "owner", "sha256", "gap_reason")


def _by_id(index: IndexDoc) -> dict[str, IndexRow]:
    return {r.row_id: r for r in index.rows}


def compute(old: IndexDoc, new: IndexDoc, from_run: str, to_run: str) -> IndexDiff:
    old_map = _by_id(old)
    new_map = _by_id(new)
    old_ids = set(old_map)
    new_ids = set(new_map)
    paired = old_ids & new_ids
    unpaired_old = old_ids - paired
    unpaired_new = new_ids - paired

    renamed: list[Rename] = []
    used_old: set[str] = set()
    used_new: set[str] = set()
    old_present = {
        i: old_map[i]
        for i in unpaired_old
        if old_map[i].status == "Present" and old_map[i].sha256
    }
    new_present = {
        i: new_map[i]
        for i in unpaired_new
        if new_map[i].status == "Present" and new_map[i].sha256
    }
    by_hash_old: dict[str, list[str]] = {}
    for rid, row in old_present.items():
        by_hash_old.setdefault(row.sha256 or "", []).append(rid)
    for nrid, nrow in new_present.items():
        cands = [oid for oid in by_hash_old.get(nrow.sha256 or "", []) if oid not in used_old]
        if len(cands) == 1:
            oid = cands[0]
            renamed.append(Rename(from_row_id=oid, to_row_id=nrid, sha256=nrow.sha256 or ""))
            used_old.add(oid)
            used_new.add(nrid)

    added = sorted(unpaired_new - used_new)
    removed = sorted(unpaired_old - used_old)
    changed: list[ChangedRow] = []
    unchanged: list[str] = []
    for rid in sorted(paired):
        a, b = old_map[rid], new_map[rid]
        fields: dict[str, FieldChange] = {}
        for name in _TRACKED:
            fv, tv = getattr(a, name), getattr(b, name)
            if fv != tv:
                fields[name] = FieldChange(**{"from": fv, "to": tv})
        if fields:
            changed.append(ChangedRow(row_id=rid, fields=fields))
        else:
            unchanged.append(rid)

    return IndexDiff(
        from_run=from_run,
        to_run=to_run,
        from_catalog_id=old.catalog_id,
        to_catalog_id=new.catalog_id,
        added=added,
        removed=removed,
        changed=changed,
        renamed=renamed,
        unchanged_ids=unchanged,
        summary={
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "renamed": len(renamed),
            "unchanged": len(unchanged),
        },
    )
