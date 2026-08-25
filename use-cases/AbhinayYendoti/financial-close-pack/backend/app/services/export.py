"""Final pack export.

`POST /export` used to flip a boolean and return three hardcoded filenames with no
bytes behind them. It now assembles a real zip containing generated PDF sheets and the
actual uploaded source documents, which the browser downloads.
"""

import base64
import io
import json
import zipfile
from typing import Any

from . import storage, superdocs_ops
from .clock import now_iso
from .memo import SUPPORTING_MEMO_NAME, build_supporting_memo_bytes
from .pdf import build_pdf

SHEETS = [
    "00-manifest.json",
    "01-close-summary.pdf",
    "02-checklist.pdf",
    "03-review-decisions.pdf",
    "04-signoffs.pdf",
    "05-audit-trail.pdf",
]

# The SuperDocs half of the pack, kept in its own directory so a reviewer can tell at a
# glance which bytes came from SuperDocs and which the app assembled.
SUPERDOCS_DIR = "superdocs"
SUPERDOCS_METADATA = f"{SUPERDOCS_DIR}/export-metadata.json"
SUPERDOCS_LEDGER = f"{SUPERDOCS_DIR}/operation-ledger.json"


def superdocs_export_entry(close: dict[str, Any]) -> str | None:
    export = close.get("superdocs_export") or {}
    filename = export.get("filename")
    return f"{SUPERDOCS_DIR}/{filename}" if filename and export.get("storage_key") else None


def planned_files(close: dict[str, Any]) -> list[str]:
    """What the pack will contain. Used by the UI before an export exists."""
    documents = [f"documents/{doc['filename']}" for doc in close["documents"] if doc["status"] == "READY"]
    superdocs = [SUPERDOCS_METADATA, SUPERDOCS_LEDGER]
    exported = superdocs_export_entry(close)
    if exported:
        superdocs.append(exported)
    return SHEETS + [SUPPORTING_MEMO_NAME] + sorted(superdocs) + sorted(documents)


def store_superdocs_export(close: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    """Persist what SuperDocs returned from `export_document`.

    A live response may hand back inline bytes, a URL, or neither. Inline bytes are
    stored and shipped; a URL is recorded as a reference. Nothing is invented to make
    the response look richer than it was.
    """
    document_id = envelope.get("document_id") or close.get("superdocs_working_document_id") or "document"
    filename = envelope.get("filename") or f"{document_id}-final.pdf"
    record: dict[str, Any] = {
        "kind": "SUPERDOCS_EXPORT",
        "mode": envelope.get("mode") or superdocs_ops.current_mode(),
        "document_id": document_id,
        "export_id": envelope.get("export_id"),
        "format": envelope.get("format"),
        "filename": filename,
        "approved_change_ids": envelope.get("approved_change_ids") or [],
        "download_url": envelope.get("download_url") or envelope.get("url"),
        "storage_key": None,
        "size": None,
        "sha256": envelope.get("sha256"),
        "retrieved_at": now_iso(),
        "envelope": superdocs_ops.redact(envelope),
    }

    encoded = envelope.get("content_base64")
    if encoded:
        try:
            content = base64.b64decode(encoded)
        except (ValueError, TypeError):
            record["note"] = "SuperDocs returned content_base64 that could not be decoded."
            return record
        key = f"exports/{close['id']}/superdocs/{filename}"
        stored = storage.put_bytes(key, content)
        record.update({"storage_key": key, "size": stored["size"], "sha256": stored["sha256"]})
        return record

    record["note"] = (
        "SuperDocs returned no inline content. The reference above is recorded, but the "
        "bytes are not fetched, so the zip ships metadata only for this file."
    )
    return record


def _summary_pdf(close: dict[str, Any], readiness: dict[str, Any]) -> bytes:
    return build_pdf(
        f"Close Pack - {close['entity']} {close['period']}",
        [
            f"Template: {close.get('template_name', close.get('template_id', ''))}",
            f"Owner: {close['owner']}",
            f"Due date: {close['due_date']}",
            f"Created: {close['created_at']} by {close['created_by']}",
            f"Closed: {close.get('closed_at') or 'not yet closed'}",
            "",
            f"Readiness: {readiness['readiness']}%",
            f"Documents: {readiness['documents']['present']} of {readiness['documents']['required']} required",
            f"Checklist: {readiness['checklist']['complete']} of {readiness['checklist']['required']} complete",
            f"Reviews: {readiness['reviews']['resolved']} of {readiness['reviews']['total']} resolved",
            f"Sign-offs: {readiness['signoffs']['approved']} of {readiness['signoffs']['required']} approved",
            "",
            "Outstanding blockers:" if readiness["blockers"] else "No outstanding blockers.",
            *[f"  - {blocker}" for blocker in readiness["blockers"]],
        ],
    )


def _checklist_pdf(close: dict[str, Any]) -> bytes:
    lines: list[str] = []
    for item in close["checklist"]:
        mark = "[x]" if item["status"] == "COMPLETE" else "[ ]"
        who = item.get("completed_by") or "unassigned"
        when = item.get("completed_at") or "-"
        lines.append(f"{mark} {item['title']}")
        lines.append(f"      evidence: {item.get('evidence', item['document_type'])}")
        lines.append(f"      completed by {who} at {when}")
    return build_pdf(f"Close Checklist - {close['period']}", lines or ["No checklist items."])


def _reviews_pdf(close: dict[str, Any]) -> bytes:
    lines: list[str] = []
    for item in close["reviews"]:
        lines.append(f"[{item['status']}] {item['section']}")
        lines.append(f"      source: {item.get('source_reference') or 'n/a'}")
        lines.append(f"      before: {item['before_value']}")
        lines.append(f"      after:  {item['after_value']}")
        lines.append(f"      decided by {item.get('reviewed_by') or '-'} at {item.get('reviewed_at') or '-'}")
        if item.get("reason"):
            lines.append(f"      reason: {item['reason']}")
    return build_pdf(f"Review Decisions - {close['period']}", lines or ["No proposed changes were generated."])


def _signoffs_pdf(close: dict[str, Any]) -> bytes:
    lines: list[str] = []
    for item in close["signoffs"]:
        lines.append(f"{item['role']}: {item.get('person') or 'unsigned'}")
        lines.append(f"      status: {item['status']}")
        lines.append(f"      signed at: {item.get('signed_at') or '-'}")
    return build_pdf(f"Sign-off Sheet - {close['period']}", lines or ["No sign-offs required."])


def _audit_pdf(close: dict[str, Any]) -> bytes:
    lines = [
        f"{entry['created_at']}  {entry['event']}  by {entry['actor']}"
        + (f"  - {entry['detail']}" if entry.get("detail") else "")
        for entry in close.get("audit", [])
    ]
    return build_pdf(f"Audit Trail - {close['period']}", lines or ["No audit events recorded."])


def _superdocs_manifest(close: dict[str, Any]) -> dict[str, Any]:
    export = close.get("superdocs_export") or None
    return {
        "mode": superdocs_ops.current_mode(),
        "working_document_id": close.get("superdocs_working_document_id"),
        "source_document_ids": close.get("superdocs_document_ids") or [],
        "contract_coverage": superdocs_ops.contract_coverage(close),
        "export": export,
        "operation_count": len(close.get("superdocs_operations") or []),
    }


def build_pack(close: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    manifest = {
        "close_id": close["id"],
        "entity": close["entity"],
        "period": close["period"],
        "generated_at": now_iso(),
        "readiness": readiness,
        "superdocs": _superdocs_manifest(close),
        "generated_artifacts": [
            {
                "name": artifact["name"],
                "kind": artifact["kind"],
                "sha256": artifact.get("sha256"),
                "size": artifact.get("size"),
                "generated_at": artifact.get("generated_at"),
            }
            for artifact in close.get("generated_artifacts") or []
        ],
        "documents": [
            {
                "filename": doc["filename"],
                "document_type": doc.get("document_type"),
                "sha256": doc.get("sha256"),
                "size": doc.get("size"),
                "uploaded_by": doc.get("uploaded_by"),
                "uploaded_at": doc.get("uploaded_at"),
            }
            for doc in close["documents"]
            if doc["status"] == "READY"
        ],
    }

    buffer = io.BytesIO()
    written: list[str] = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("00-manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("01-close-summary.pdf", _summary_pdf(close, readiness))
        archive.writestr("02-checklist.pdf", _checklist_pdf(close))
        archive.writestr("03-review-decisions.pdf", _reviews_pdf(close))
        archive.writestr("04-signoffs.pdf", _signoffs_pdf(close))
        archive.writestr("05-audit-trail.pdf", _audit_pdf(close))
        written.extend(SHEETS)

        # The Supporting Memo is rebuilt here rather than read back from storage so the
        # packaged copy always reflects the decisions this pack is being filed against.
        archive.writestr(SUPPORTING_MEMO_NAME, build_supporting_memo_bytes(close, readiness))
        written.append(SUPPORTING_MEMO_NAME)

        superdocs_export = close.get("superdocs_export") or {}
        archive.writestr(
            SUPERDOCS_METADATA,
            json.dumps(superdocs_export or {"note": "No SuperDocs export recorded."}, indent=2),
        )
        archive.writestr(
            SUPERDOCS_LEDGER,
            json.dumps(
                {
                    "close_id": close["id"],
                    "coverage": superdocs_ops.contract_coverage(close),
                    "operations": close.get("superdocs_operations") or [],
                },
                indent=2,
            ),
        )
        written.extend([SUPERDOCS_METADATA, SUPERDOCS_LEDGER])

        entry = superdocs_export_entry(close)
        if entry:
            try:
                archive.writestr(entry, storage.get_bytes(superdocs_export["storage_key"]))
                written.append(entry)
            except FileNotFoundError:
                placeholder = f"{SUPERDOCS_DIR}/MISSING-{superdocs_export['filename']}.txt"
                archive.writestr(
                    placeholder,
                    f"The SuperDocs export was recorded at {superdocs_export['storage_key']} "
                    "but the bytes were not found when the pack was assembled.",
                )
                written.append(placeholder)

        for document in close["documents"]:
            if document["status"] != "READY":
                continue
            try:
                content = storage.get_bytes(document["storage_key"])
            except FileNotFoundError:
                # Record the gap rather than silently shipping an incomplete pack.
                placeholder = f"documents/MISSING-{document['filename']}.txt"
                archive.writestr(
                    placeholder,
                    f"Source bytes for {document['filename']} were not found at "
                    f"{document['storage_key']} when the pack was assembled.",
                )
                written.append(placeholder)
                continue
            entry = f"documents/{document['filename']}"
            archive.writestr(entry, content)
            written.append(entry)

    filename = f"close-pack-{close['entity'].replace(' ', '-').lower()}-{close['period']}.zip"
    key = f"exports/{close['id']}/{filename}"
    stored = storage.put_bytes(key, buffer.getvalue())

    return {
        "kind": "APP_ZIP",
        "storage_key": key,
        "filename": filename,
        "size": stored["size"],
        "sha256": stored["sha256"],
        "generated_at": manifest["generated_at"],
        "files": written,
    }
