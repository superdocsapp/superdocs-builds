"""Live end-to-end QA against the running server on :8000 (Phase 13).

Executes the full 28-step sequence: create packet, upload six PII-bearing
documents, privilege marking (incl. wrong-packet 404 regression), detect with
account/name verification, idempotent re-detect, approve/apply-all, validate,
build, manifest SHA checks, PII-free artifact scan, idempotent rebuild,
corrupt-upload orphan check, invalid-UUID 422, packet delete with storage/DB
cleanup, audit trail, and live SuperDocs AI analyze with session reuse.
"""

import asyncio
import json
import os
import sys
import uuid

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app", "tests"))
from qa_helpers import (
    PII_FIXTURES,
    assert_artifacts_pii_free,
    make_pdf,
    sha256_of,
)

BASE = "http://127.0.0.1:8000"
STORAGE_ROOT = os.path.join(os.path.dirname(__file__), "storage")

PRIVILEGED_LINES = [
    "CONFIDENTIAL ATTORNEY CLIENT PRIVILEGED",
    "RE: Settlement Strategy",
    "Legal advice from counsel regarding negotiation positions.",
    "No PII contained in this privileged memo.",
]
CONTRACT_LINES = [
    "CONTRACT FOR SERVICES",
    "Parties: Jane Smith and John Doe",
    "Employee SSN: 123-45-6789",
    "Contact email: jane.public@example.com",
    "Phone: (212) 555-0199",
    "Term: 2026-08-01 to 2027-07-31",
]
INVOICE_LINES = [
    "INVOICE NO. INV-2026-001",
    "Account number: ACC-8821-4433",
    "Client account: 8821-4433-2211-9900",
    "Alternate: ACC 8821 4433",
    "Statement ref: FQ-0500",
    "Page One",
]
EMAIL_LINES = [
    "FROM: jane.public@example.com",
    "TO: john.doe@example.net",
    "RE: Contract renewal",
    "Attached are the revised terms for review.",
]
BUSINESS_LINES = [
    "BUSINESS RECORD",
    "Prepared by John Doe on 2026-07-10",
    "Account: ACCOUNT-8821-4433",
    "SSN: 987-65-4321",
]
SUMMARY_LINES = [
    "NONPRIVILEGED SUMMARY",
    "Monthly activity overview for the account.",
    "No sensitive data in this summary.",
]

FIXTURES = [
    ("contract.pdf", CONTRACT_LINES, 3),
    ("privileged_memo.pdf", PRIVILEGED_LINES, 1),
    ("invoice.pdf", INVOICE_LINES, 2),
    ("email_thread.pdf", EMAIL_LINES, 2),
    ("business_record.pdf", BUSINESS_LINES, 1),
    ("activity_summary.pdf", SUMMARY_LINES, 1),
]

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")
    return condition


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        from app.config import get_settings
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(get_settings().database_url)

        async def db_count(table):
            async with engine.begin() as conn:
                r = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                return r.scalar()

        async def audit(packet_id):
            r = await client.get(f"/api/audit/{packet_id}")
            return r.json()["events"]

        originals_dir = os.path.join(STORAGE_ROOT, "originals")
        clean_originals = sorted(
            os.listdir(originals_dir)) if os.path.isdir(originals_dir) else []

        print("== 1-7. Create packet and upload six documents ==")
        r = await client.post("/api/packets", json={
            "name": "Phase13 Live E2E Packet", "bates_prefix": "E2E-",
            "bates_start_number": 1000, "bates_padding": 4,
        })
        check("create packet", r.status_code == 200, r.text)
        packet_id = r.json()["id"]

        doc_ids = {}
        for i, (fname, lines, pages) in enumerate(FIXTURES):
            body = make_pdf(lines, page_count=pages)
            files = {"files": (fname, body, "application/pdf")}
            r = await client.post(f"/api/documents/{packet_id}/upload", files=files)
            ok = r.status_code == 200
            check(f"upload {fname} ({pages} pages)", ok, r.text)
            if ok:
                d = r.json()["documents"][0]
                doc_ids[fname] = d["id"]
                check(f"{fname} completed", d["status"] == "completed", d["status"])
                check(f"{fname} page_count", d["page_count"] == pages, d["page_count"])

        print("== 8. Document list with bates ranges ==")
        r = await client.get(f"/api/documents/{packet_id}")
        docs = r.json()
        check("six documents listed", len(docs) == 6, len(docs))
        check("bates starts E2E-1000", docs[0]["bates_range"] == "E2E-1000 - E2E-1002",
              docs[0]["bates_range"])
        check("bates ends E2E-1009", docs[-1]["bates_range"] == "E2E-1009 - E2E-1009",
              docs[-1]["bates_range"])

        print("== 9-13. Privilege marking (C-1 live) ==")
        memo_id = doc_ids["privileged_memo.pdf"]
        contract_id = doc_ids["contract.pdf"]

        r = await client.post(f"/api/privilege/{packet_id}/{memo_id}", json={
            "status": "privileged", "reason": "Attorney client communication",
            "marked_by": "qa-senior", "reviewer": "qa-supervisor", "category": "attorney_client",
        })
        check("mark memo privileged", r.status_code == 200, r.text)

        r = await client.post(f"/api/privilege/{packet_id}/{contract_id}", json={
            "status": "not_privileged", "reason": "Business contract, no legal advice",
            "marked_by": "qa-senior", "reviewer": "qa-supervisor",
        })
        check("mark contract not privileged", r.status_code == 200, r.text)

        r = await client.get(f"/api/privilege/{packet_id}/log")
        log = r.json()
        log_entries = log["entries"]
        check("privilege log has 1 privileged entry", len(log_entries) == 1, len(log_entries))
        check("log contains privileged memo", any(d["document_id"] == memo_id and d["privilege_category"] == "attorney_client" for d in log_entries), log_entries)

        r = await client.patch(f"/api/privilege/{packet_id}/{memo_id}", json={
            "status": "privileged", "reason": "Confirmed work product",
            "marked_by": "qa-senior", "reviewer": "qa-supervisor", "category": "work_product",
        })
        check("patch override memo", r.status_code == 200, r.text)
        r = await client.get(f"/api/privilege/{packet_id}/log")
        log_entries = r.json()["entries"]
        check("override kept 1 entry", len(log_entries) == 1, len(log_entries))
        updated = log_entries[0]
        check("override changed category", updated["privilege_category"] == "work_product", updated)

        wrong = uuid.uuid4()
        r = await client.post(f"/api/privilege/{wrong}/{memo_id}", json={
            "status": "privileged", "reason": "x", "marked_by": "qa", "reviewer": "qa-supervisor",
        })
        check("wrong packet -> 404 (C-1)", r.status_code == 404, r.text)

        print("== 14-17. Detection incl. H-1 account patterns ==")
        r = await client.post(f"/api/redactions/{packet_id}/detect")
        check("detect queued", r.status_code == 200, r.text)
        check("6 documents queued", r.json()["documents_queued"] == 6, r.json())

        await asyncio.sleep(3.0)
        r = await client.get(f"/api/redactions/{packet_id}")
        candidates = r.json()
        c1 = len(candidates)
        matched = {c["matched_text"] for c in candidates}
        print(f"       candidates: {c1}")

        for expected in ["ACC-8821-4433", "ACC 8821 4433", "ACCOUNT-8821-4433",
                         "8821-4433-2211-9900", "123-45-6789", "987-65-4321",
                         "jane.public@example.com", "(212) 555-0199", "Jane Smith", "John Doe"]:
            check(f"detected {expected!r}", expected in matched, sorted(matched)[:20])

        for absent in ["FQ-0500", "2026-08-01", "Page One", "INV-2026-001"]:
            check(f"no false positive {absent!r}", absent not in matched, absent)

        r = await client.post(f"/api/redactions/{packet_id}/detect")
        check("re-detect accepted", r.status_code == 200, r.text)
        await asyncio.sleep(2.0)
        r = await client.get(f"/api/redactions/{packet_id}")
        c2 = len(r.json())
        check("re-detect idempotent (M-2)", c2 == c1, f"{c1} -> {c2}")

        print("== 18-20. Approve and apply all ==")
        for c in r.json():
            resp = await client.post(f"/api/redactions/{c['id']}/approve",
                                     json={"status": "approved", "approver": "qa-reviewer"})
            assert resp.status_code == 200, resp.text
        r = await client.post(f"/api/redactions/{packet_id}/apply-all",
                              json={"document_ids": list(doc_ids.values())})
        check("apply-all ok", r.status_code == 200, r.text)
        results = r.json()["results"]
        check("docs with candidates applied", len(results) == 5, results)
        all_verified = all(
            all(c["verified"] for c in doc_result["verification"].values())
            and doc_result["candidates_failed"] == 0
            for doc_result in results
        )
        check("all applied verified", all_verified, results)

        r = await client.get(f"/api/redactions/{packet_id}")
        check("all candidates applied", all(c["status"] == "applied" for c in r.json()), r.json()[:1])

        print("== 21-25. Validate, build, manifest, PII scan, rebuild ==")
        r = await client.post(f"/api/exports/{packet_id}/validate")
        check("validate ok", r.status_code == 200 and r.json()["valid"], r.text)
        r = await client.post(f"/api/exports/{packet_id}/build")
        check("build ok", r.status_code == 200, r.text)
        build = r.json()

        final_dir = os.path.join(STORAGE_ROOT, "final", packet_id)
        final_packet = os.path.join(final_dir, "final_packet.pdf")
        check("final_packet exists", os.path.exists(final_packet))

        def sha_of(path):
            with open(path, "rb") as f:
                return sha256_of(f.read())

        r = await client.get(f"/api/exports/{packet_id}/manifest")
        manifest = r.json()
        check("manifest sha matches final packet",
              manifest["final_packet_sha256"] == sha_of(final_packet))
        for e in manifest["entries"]:
            p = os.path.join(final_dir, "exhibits", os.path.basename(e["final_file_path"]))
            if not check(f"exhibit sha {e['exhibit_identifier']}", e["final_sha256"] == sha_of(p), p):
                break
        check("manifest total docs 6", manifest["total_documents"] == 6, manifest["total_documents"])
        check("manifest privileged entry present",
              any(e["privilege_status"] == "privileged" for e in manifest["entries"]))
        memo_entry = next(e for e in manifest["entries"] if e["privilege_status"] == "privileged")
        check("memo entry bates E2E-1003", memo_entry["bates_start"] == "E2E-1003", memo_entry)
        check("memo entry category work_product",
              memo_entry["privilege_category"] == "work_product", memo_entry)

        try:
            assert_artifacts_pii_free(final_dir, PII_FIXTURES)
            check("artifacts PII-free (final/cover/index/log/EX-*/manifest)", True)
        except AssertionError as e:
            check("artifacts PII-free (final/cover/index/log/EX-*/manifest)", False, str(e))

        r = await client.post(f"/api/exports/{packet_id}/build")
        check("rebuild ok", r.status_code == 200, r.text)
        r = await client.get(f"/api/exports/{packet_id}/manifest")
        new_manifest = r.json()
        check("rebuild manifest matches new file",
              new_manifest["final_packet_sha256"] == sha_of(final_packet),
              "manifest sha does not match rebuilt file")
        try:
            assert_artifacts_pii_free(final_dir, PII_FIXTURES)
            check("rebuilt artifacts PII-free", True)
        except AssertionError as e:
            check("rebuilt artifacts PII-free", False, str(e))

        print("== 26-27. Corrupt upload and invalid UUID ==")
        originals_dir = os.path.join(STORAGE_ROOT, "originals")
        originals = [f for f in os.listdir(originals_dir)]
        files = {"files": ("broken.pdf", b"%PDF-1.4\nfake\n%%EOF", "application/pdf")}
        r = await client.post(f"/api/documents/{packet_id}/upload", files=files)
        check("corrupt upload 400", r.status_code == 400, r.text)
        after = [f for f in os.listdir(originals_dir)]
        check("no new orphan file on corrupt upload (M-4)",
              after == originals,
              f"originals changed: {originals} -> {after}")

        r = await client.post("/api/redactions/not-a-uuid/detect")
        check("invalid UUID detect -> 422", r.status_code == 422, r.text)
        r = await client.post(f"/api/documents/not-a-uuid/upload", files=files)
        check("invalid UUID upload -> 422", r.status_code == 422, r.text)

        print("== 28. Live SuperDocs AI analysis + session reuse ==")
        business_id = doc_ids["business_record.pdf"]
        r = await client.post(
            f"/api/review/{packet_id}/documents/{business_id}/analyze",
            json={"instruction": "Summarize this business record"},
        )
        check("AI analyze started", r.status_code == 200, r.text)
        job_id = r.json()["job_id"]
        check("AI job id present", bool(job_id), r.text)

        for attempt in range(30):
            r = await client.get(
                f"/api/review/{packet_id}/documents/{business_id}/analysis-status",
                params={"job_id": job_id},
            )
            status = r.json()["status"]
            if status in ("completed", "failed"):
                break
            await asyncio.sleep(5)
        check("AI poll completed", status == "completed", f"{job_id} -> {status}")

        async with engine.begin() as conn:
            row = (await conn.execute(
                text("SELECT superdocs_session_id, superdocs_document_id, processing_status "
                     "FROM documents WHERE id = :id"), {"id": business_id})).first()
        check("superdocs session persisted", bool(row[0] and row[1]), row)
        check("doc completed after AI", row[2].upper() == "COMPLETED", row)

        r = await client.post(
            f"/api/review/{packet_id}/documents/{business_id}/analyze",
            json={"instruction": "Summarize again"},
        )
        check("re-analyze reuses session", r.status_code == 200, r.text)
        async with engine.begin() as conn:
            row2 = (await conn.execute(
                text("SELECT superdocs_session_id FROM documents WHERE id = :id"),
                {"id": business_id})).first()
        check("session unchanged after re-analyze", row2[0] == row[0], (row[0], row2[0]))

        print("== Audit trail ==")
        events = await audit(packet_id)
        types = [e["event_type"] for e in events]
        for expected in ["packet_created", "upload", "processing_started", "processing_completed",
                         "bates_assigned", "privilege_marked", "redaction_proposed",
                         "redaction_approved", "redaction_applied", "redaction_verified",
                         "packet_validated", "packet_built", "ai_analysis_started",
                         "ai_analysis_completed"]:
            check(f"audit {expected}", expected in types, types[:10])
        marked = [e for e in events if e["event_type"] == "privilege_marked"]
        actions = sorted(e["metadata"]["action"] for e in marked)
        check("privilege audit actions created/updated", actions == ["created", "created", "updated"],
              actions)
        validated = [e for e in events if e["event_type"] == "packet_validated"]
        check("packet_validated metadata", validated and validated[0]["metadata"]["valid"] is True,
              validated[0] if validated else None)
        proposed = [e for e in events if e["event_type"] == "redaction_proposed"]
        check("redaction_proposed candidates_found", proposed and proposed[-1]["metadata"]["candidates_found"] > 0,
              proposed[-1] if proposed else None)
        check("redaction_proposed 2nd run created 0",
              len(proposed) >= 2 and proposed[0]["metadata"]["candidates_created"] == 0,
              proposed[0] if proposed else None)

        print("== 29. Delete packet, cleanup ==")
        r = await client.delete(f"/api/packets/{packet_id}")
        check("delete packet", r.status_code == 200, r.text)
        await asyncio.sleep(1.0)

        for table in ["packets", "documents", "pages", "bates_assignments",
                      "redaction_candidates", "redaction_approvals", "privilege_decisions",
                      "manifests", "manifest_entries"]:
            check(f"table {table} empty", await db_count(table) == 0, await db_count(table))

        check("final dir removed", not os.path.isdir(final_dir))
        remaining = sorted(os.listdir(originals_dir)) if os.path.isdir(originals_dir) else []
        check("no new originals left", remaining == clean_originals, remaining)
        async with engine.begin() as conn:
            deleted_rows = (await conn.execute(
                text("SELECT event_metadata FROM audit_events WHERE event_type = 'PACKET_DELETED'"))).all()
        check("packet_deleted audit row kept",
              len(deleted_rows) >= 1 and deleted_rows[-1][0]["packet_name"] == "Phase13 Live E2E Packet",
              deleted_rows)

        await engine.dispose()

    print()
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)


asyncio.run(main())
