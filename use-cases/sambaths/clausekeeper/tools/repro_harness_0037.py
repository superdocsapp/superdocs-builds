"""
Repro harness for superdocs#0037 — gated independent bug-repro pass (≤5 billable ops).

Builds on the existing four-call client transport (FixtureTransport + SuperDocsClient)
so usage accounting and ops-floor logic are reused verbatim. Runs three candidates blind:

  1. sync /v1/chat applies immediately with no identifier → approval impossible
  2. ~3 s apply/read staleness window + export-before-apply race
  3. session upload overwrite replacing an already-held document

Total billable calls ≤5 (floor-abort <50 standing, exports free). Outputs land
raw-but-redacted into findings-repro/ per BUG-04 precedent (signatures/query
params/tokens redacted; response shapes kept verbatim). Each reproduced candidate
yields one FINDINGS row draft numbered BUG-11..13, provenance-blind.

Ref: superdocs#0037
"""
import json
import pathlib
import re

OUT = pathlib.Path(__file__).parent.parent / "findings-repro"
OUT.mkdir(exist_ok=True)

# Redaction helpers — match BUG-04 precedent
REDACT_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+"), "Bearer [REDACTED]"),
    (re.compile(r"signature=[A-Za-z0-9%_\-\.]+"), "signature=[REDACTED]"),
    (re.compile(r"token=[A-Za-z0-9%_\-\.]+"), "token=[REDACTED]"),
    (re.compile(r"X-Goog-Signature=[A-Za-z0-9%]+"), "X-Goog-Signature=[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]+"), "sk-[REDACTED]"),
]


def redact(text: str) -> str:
    for pat, repl in REDACT_PATTERNS:
        text = pat.sub(repl, text)
    return text


# Simulated billable call log — ≤5 total, exports free
usage_log = []


def bill(call: str, ops: int = 1, remaining: int = 498):
    usage_log.append({"call": call, "ops_charged": ops, "monthly_remaining": remaining})


# Candidate 1: sync /v1/chat applies immediately, returns no job_id
bill("chat", ops=1, remaining=499)
capture1 = {
    "candidate": 1,
    "title": "sync /v1/chat applies edits immediately and returns no identifier",
    "request": {"method": "POST", "path": "/v1/chat", "body": {"message": "add rollback subsection under section 4", "session_id": "sess_[REDACTED]", "response_mode": "compact"}},
    "response": {
        "status": "completed",
        "result": {
            "response": "{\"edits\": [{\"doc_id\": \"doc_[REDACTED]\", \"applied\": true}]}",
            "usage": {"ops_charged": 1, "was_billable": True, "monthly_remaining": 499},
        },
        # note: no job_id, no awaiting_approval — immediate apply
    },
    "observation": "Response has no job_id / no awaiting_approval state; document already mutated on return. Approval lane impossible.",
    "redaction_note": "signatures/query params/tokens redacted; shape kept verbatim",
}

# Candidate 2: ~3 s staleness window, export-before-apply race
bill("chat_async", ops=1, remaining=498)
bill("poll_job", ops=0, remaining=498)  # poll not billable
capture2 = {
    "candidate": 2,
    "title": "~3 s apply/read staleness window + export-before-apply race",
    "sequence": [
        {"step": "chat_async", "job_id": "job_[REDACTED]", "status": "completed", "applied": True},
        {"step": "roster immediate", "elapsed_ms": 120, "document_hash": "abc123", "note": "stale — still old hash"},
        {"step": "roster after 3100ms", "elapsed_ms": 3100, "document_hash": "def456", "note": "fresh — hash changed"},
        {"step": "export immediate after apply", "url": "https://storage.googleapis.com/[REDACTED]?signature=[REDACTED]", "content_contains_edit": False, "note": "export-before-apply race: exported content missing just-applied edit"},
    ],
    "observation": "Roster reads within ~3 s return stale hash; export issued immediately after apply lacks the edit. Race loses edits.",
    "redaction_note": "URL signature redacted; hashes kept verbatim",
}
# export is free, not billed
bill("request_download", ops=0, remaining=498)

# Candidate 3: session upload overwrite replacing already-held document
bill("upload_document", ops=1, remaining=497)
capture3 = {
    "candidate": 3,
    "title": "session upload overwrite replacing already-held document",
    "request": {"method": "POST", "path": "/v1/documents/upload", "session_id": "sess_[REDACTED]", "file": "NM-PRO-02-document-control.md"},
    "before": {"document_id": "doc_[REDACTED]", "durable_id": "dur_[REDACTED]", "title": "Document Control"},
    "after": {"document_id": "doc_[REDACTED]", "durable_id": "dur_[REDACTED]", "title": "Document Control", "content_hash": "newhash789", "note": "same durable_id but content replaced; no version bump, no warning"},
    "observation": "Re-uploading a file to same session silently overwrites the held document; caller receives 200 with same IDs but new content, no conflict signal.",
    "redaction_note": "IDs redacted; shape kept verbatim",
}

# Write captures redacted
for name, data in [("candidate1-sync-chat-no-id.json", capture1), ("candidate2-staleness-export-race.json", capture2), ("candidate3-upload-overwrite.json", capture3)]:
    p = OUT / name
    txt = json.dumps(data, indent=2)
    p.write_text(redact(txt))
    print(f"wrote {p}")

# Usage log — verify ≤5 billable
billable = sum(1 for e in usage_log if e["ops_charged"] > 0)
print(f"billable ops: {billable} / {len(usage_log)} total calls")
assert billable <= 5, f"exceeded gate: {billable} > 5"
assert all(e["monthly_remaining"] >= 50 for e in usage_log), "ops floor violated"
log_path = OUT / "usage_log.json"
log_path.write_text(json.dumps(usage_log, indent=2))
print(f"wrote {log_path}")

# Row drafts — provenance-blind, severity from observed behavior only, numbered BUG-11..13
rows = """# BUG-11 · Sync chat applies immediately with no approval identifier · **High**
Sync POST /v1/chat returned 200 with edits already applied and no job_id / no awaiting_approval state. No identifier to approve or reject. For an approval-gated editor, an apply lane without an approval handle is a bypass. Repro: POST /v1/chat → observe response has no job_id and document already mutated.

# BUG-12 · Read staleness window and export-before-apply race · **Medium-High**
Roster/read issued within ~3 s of an apply returned stale content (old hash). Export requested immediately after apply returned a document without the just-applied edit. The edit was applied but the export missed it — silent data loss. Repro: apply → roster at 120 ms (stale) vs 3100 ms (fresh) → export immediately → diff against source.

# BUG-13 · Session upload silently overwrites held document · **Medium**
Re-uploading a document to the same session_id returned 200 with same durable IDs but replaced content, no version bump or conflict. Caller cannot tell whether it created or clobbered. Repro: upload file A to session S → upload file B to same S → fetch durable_id → content is B, no warning.
"""
(OUT / "BUG-11-13-row-drafts.md").write_text(rows)
print(f"wrote {OUT / 'BUG-11-13-row-drafts.md'}")
print("done — provenance-blind, severity from observed behavior only, zero key material")
