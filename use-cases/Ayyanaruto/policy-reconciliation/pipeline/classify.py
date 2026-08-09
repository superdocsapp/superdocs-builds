"""Stage 4–5: attach local decisions, quote conflicts verbatim, prove coverage."""

from __future__ import annotations

from pathlib import Path

from .common import DISPOSITIONS, RECOMMENDATIONS, client


def decide(pair):
    """Map SuperDocs judgment to keep_a | keep_b | merge | new. Conflicts are never auto-merged."""
    rec = str((pair or {}).get("recommendation") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if rec not in RECOMMENDATIONS:
        rec = "new"
    if rec == "merge" and (pair or {}).get("conflict"):
        return "new"
    return rec


def _default_title(doc_a, doc_b):
    a = (doc_a or {}).get("stem") or "estate-a"
    b = (doc_b or {}).get("stem") or "estate-b"
    return f"{a} / {b}"


def _doc_ref(doc):
    if not doc:
        return None
    return {
        "filename": doc["filename"],
        "stem": doc["stem"],
        "path": doc["path"],
        "session_id": doc["session_id"],
        "document_id": doc.get("document_id"),
    }


def classify(match_payload, docs):
    """Attach a local decision to each SuperDocs policy pairing."""
    docs_by_name = {(doc["estate"], doc["filename"]): doc for doc in docs}

    def resolve(estate, filename):
        if not filename:
            return None
        found = docs_by_name.get((estate, filename))
        if found:
            return found
        stem = Path(str(filename)).stem.lower()
        for (est, name), doc in docs_by_name.items():
            if est == estate and Path(name).stem.lower() == stem:
                return doc
        return None

    policies = []
    for i, raw in enumerate(match_payload.get("policies") or [], start=1):
        if not isinstance(raw, dict):
            continue
        rec = decide(raw)
        doc_a = resolve("a", raw.get("doc_a_filename") or raw.get("doc_a"))
        doc_b = resolve("b", raw.get("doc_b_filename") or raw.get("doc_b"))
        policies.append(
            {
                "id": str(raw.get("id") or f"map_{i:03d}"),
                "title": raw.get("title") or _default_title(doc_a, doc_b),
                "doc_a": _doc_ref(doc_a),
                "doc_b": _doc_ref(doc_b),
                "recommendation": rec,
                "superdocs_recommendation": raw.get("recommendation"),
                "evidence": (raw.get("evidence") or "").strip(),
                "obligation_ids_a": list(raw.get("obligation_ids_a") or []),
                "obligation_ids_b": list(raw.get("obligation_ids_b") or []),
                "conflict": bool(raw.get("conflict")),
            }
        )
    return {"policies": policies}


def detect_conflicts(obligations, match_payload):
    """Build conflict records with verbatim extract excerpts — never SuperDocs paraphrase."""
    by_id = {o["id"]: o for o in obligations}
    conflicts = []
    for i, raw in enumerate(match_payload.get("conflicts") or [], start=1):
        if not isinstance(raw, dict):
            continue
        id_a = raw.get("obligation_a_id")
        id_b = raw.get("obligation_b_id")
        obl_a = by_id.get(id_a)
        obl_b = by_id.get(id_b)
        if not obl_a or not obl_b:
            continue
        conflicts.append(
            {
                "id": str(raw.get("id") or f"conflict_{i:03d}"),
                "obligation_a_id": obl_a["id"],
                "obligation_b_id": obl_b["id"],
                "policy_a_excerpt": obl_a["text"],
                "policy_b_excerpt": obl_b["text"],
                "reason": (raw.get("reason") or "").strip(),
                "document_a": obl_a.get("document_filename"),
                "document_b": obl_b.get("document_filename"),
                "chunk_id_a": obl_a.get("chunk_id"),
                "chunk_id_b": obl_b.get("chunk_id"),
            }
        )
    return {"conflicts": conflicts}


def build_coverage(obligations, match_payload, docs):
    """Tag every extracted obligation. Totals must reconcile against extract + input docs."""
    declared = {}
    for row in match_payload.get("coverage") or []:
        if not isinstance(row, dict):
            continue
        obl_id = row.get("obligation_id") or row.get("id")
        disp = str(row.get("disposition") or "").strip()
        if obl_id and disp in DISPOSITIONS:
            declared[str(obl_id)] = disp

    items = []
    counts = {"mapped": 0, "gap_a_only": 0, "gap_b_only": 0}
    for obl in obligations:
        disp = declared.get(obl["id"])
        if disp is None:
            disp = "gap-A-only" if obl["estate"] == "a" else "gap-B-only"
        items.append({**obl, "disposition": disp})
        if disp == "mapped":
            counts["mapped"] += 1
        elif disp == "gap-A-only":
            counts["gap_a_only"] += 1
        else:
            counts["gap_b_only"] += 1

    n_a = sum(1 for o in obligations if o["estate"] == "a")
    n_b = sum(1 for o in obligations if o["estate"] == "b")
    docs_a = sum(1 for d in docs if d["estate"] == "a")
    docs_b = sum(1 for d in docs if d["estate"] == "b")
    coverage = {
        "totals": {
            "documents_a": docs_a,
            "documents_b": docs_b,
            "documents_total": docs_a + docs_b,
            "obligations_a": n_a,
            "obligations_b": n_b,
            "obligations_total": len(obligations),
            "mapped": counts["mapped"],
            "gap_a_only": counts["gap_a_only"],
            "gap_b_only": counts["gap_b_only"],
        },
        "obligations": items,
    }
    total_disp = counts["mapped"] + counts["gap_a_only"] + counts["gap_b_only"]
    if total_disp != len(obligations):
        raise client.SuperDocsError(
            f"Coverage totals {total_disp} do not equal extract count {len(obligations)}"
        )
    return coverage
