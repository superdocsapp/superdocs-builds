"""
End-to-end test of main.py's business logic against an in-memory SQLite
database and fake SuperDocs/LLM clients -- no live keys, no external
Postgres. Exercises the full Workspace -> upload -> Analyze References ->
validate -> update-request -> approve -> propagate -> approve -> report
loop described in the architecture chat, using the real endpoint
functions (not a black-box HTTP client), matching this project's existing
"pure function / mocked client" testing philosophy.
"""

from __future__ import annotations

import base64

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import db
import main
import models
from tests.fakes import FakeLLMClient, FakeSuperDocsClient

POLICY_HTML_V1 = (
    '<div data-chunk-id="p1"><h2>Access Control</h2><p>Provision access within 5 business days of approval.</p></div>'
    '<div data-chunk-id="p2"><h2>Breach Notification</h2><p>Report breaches within 60 hours of discovery.</p></div>'
)
POLICY_HTML_V2 = (
    '<div data-chunk-id="p1"><h2>Access Control</h2><p>Provision access within 5 business days of approval.</p></div>'
    '<div data-chunk-id="p2"><h2>Breach Notification</h2><p>Report breaches within 24 hours of discovery.</p></div>'
)
PROCEDURE_HTML = (
    '<div data-chunk-id="c1"><h2>Reporting Steps</h2>'
    "<p>Report the incident within 60 hours of discovery to the Privacy Officer.</p></div>"
)
PROCEDURE_HTML_UPDATED = (
    '<div data-chunk-id="c1"><h2>Reporting Steps</h2>'
    "<p>Report the incident within 24 hours of discovery to the Privacy Officer.</p></div>"
)


@pytest.fixture()
def engine():
    # StaticPool: the Analyze References endpoint fans work out across a
    # ThreadPoolExecutor, so the in-memory sqlite DB needs to be shared
    # across threads/connections rather than each connection getting its
    # own (default) private in-memory database.
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(autouse=True)
def patched_db(monkeypatch, engine):
    monkeypatch.setattr(db, "get_engine", lambda: engine)


@pytest.fixture()
def fake_client(monkeypatch):
    client = FakeSuperDocsClient()
    monkeypatch.setattr(main, "get_client", lambda: client)
    return client


@pytest.fixture()
def fake_llm(monkeypatch):
    llm = FakeLLMClient()
    monkeypatch.setattr(main, "get_llm_client", lambda: llm)
    return llm


def _b64(html: str) -> str:
    return base64.b64encode(html.encode("utf-8")).decode("ascii")


def test_full_lifecycle(fake_client, fake_llm):
    # -- 1. workspace ------------------------------------------------------
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="ABC Medical Center", pack_name="Compliance Pack"))
    workspace_id = ws["id"]
    assert ws["status"] == models.WorkspaceStatus.SETUP

    # -- 2. upload policy ----------------------------------------------------
    policy_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(
            filename="billing-policy.html", file_base64=_b64(POLICY_HTML_V1), doc_type="policy", title="Billing Policy"
        ),
    )
    policy_id = policy_resp["document"]["id"]
    assert len(policy_resp["sections"]) == 2

    # -- 3. upload + group procedure -----------------------------------------
    proc_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(
            filename="breach-procedure.html", file_base64=_b64(PROCEDURE_HTML), doc_type="procedure",
            title="Breach Notification Procedure", parent_policy_id=policy_id,
        ),
    )
    proc_id = proc_resp["document"]["id"]
    assert proc_resp["document"]["parent_policy_id"] == policy_id

    docs = main.list_workspace_documents(workspace_id)
    assert {d["id"] for d in docs} == {policy_id, proc_id}

    # -- 4. analyze references (fake LLM finds the real relationship) -------
    policy_sections = main.get_document(policy_id)["sections"]
    proc_sections = main.get_document(proc_id)["sections"]
    breach_section_id = next(s["id"] for s in policy_sections if s["title"] == "Breach Notification")
    reporting_section_id = next(s["id"] for s in proc_sections if s["title"] == "Reporting Steps")

    fake_llm.set_canned(
        "Billing Policy", "Breach Notification Procedure",
        [(reporting_section_id, breach_section_id, 0.94, "Both require reporting within the same window.")],
    )

    analysis = main.analyze_references(workspace_id)
    assert analysis["jobs"][0]["status"] == models.AnalysisJobStatus.COMPLETE
    assert fake_llm.calls == [("Billing Policy", "Breach Notification Procedure")]

    refs = main.list_references(workspace_id)
    assert len(refs) == 1
    assert refs[0]["status"] == models.ReferenceStatus.VALID
    assert refs[0]["confidence"] == 0.94
    reference_id = refs[0]["id"]

    ws_after_analysis = main.get_workspace(workspace_id)
    assert ws_after_analysis["status"] == models.WorkspaceStatus.READY

    # -- 5. validate: everything should pass, no findings --------------------
    validation = main.validate_workspace(workspace_id)
    assert validation["overall_status"] == "pass"
    findings = main.list_findings(workspace_id, status=models.FindingStatus.OPEN)
    assert findings == []

    # -- 6. update request on the policy (tighten §2 60h -> 24h) -------------
    fake_client.queue_job_result(
        {
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": "chg-policy-1",
                        "operation": "edit",
                        "chunk_id": "p2",
                        "old_html": "<p>Report breaches within 60 hours of discovery.</p>",
                        "new_html": "<p>Report breaches within 24 hours of discovery.</p>",
                        "ai_explanation": "Tightened the reporting window.",
                    }
                ]
            },
        }
    )
    ur_resp = main.create_update_request(
        policy_id, main.UpdateRequestCreate(instruction="Tighten breach notification to 24 hours")
    )
    policy_pc_id = ur_resp["proposed_change"]["id"]

    pending = main.list_proposed_changes(workspace_id, status="pending")
    policy_pc = next(pc for pc in pending if pc["id"] == policy_pc_id)
    assert policy_pc["old_html"] == "<p>Report breaches within 60 hours of discovery.</p>"
    assert policy_pc["section_id"] == breach_section_id

    # -- 7. approve the policy change -- simulate SuperDocs having applied it,
    #       and queue the procedure propagation's job result BEFORE approving,
    #       since approval triggers chat_async for the affected procedure
    #       synchronously inside the same call.
    durable_policy_id = policy_resp["document"]["superdocs_document_id"]
    fake_client.html[durable_policy_id] = POLICY_HTML_V2
    fake_client.queue_job_result(
        {
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": "chg-proc-1",
                        "operation": "edit",
                        "chunk_id": "c1",
                        "old_html": "<p>Report the incident within 60 hours of discovery to the Privacy Officer.</p>",
                        "new_html": "<p>Report the incident within 24 hours of discovery to the Privacy Officer.</p>",
                        "ai_explanation": "Matched the new policy window.",
                    }
                ]
            },
        }
    )

    approve_resp = main.approve_proposed_change(policy_pc_id, main.ApproveRequest(approved=True))
    assert approve_resp["proposed_change"]["status"] == models.ProposedChangeStatus.APPROVED
    assert len(approve_resp["propagated"]) == 1
    proc_pc_id = approve_resp["propagated"][0]["proposed_change_id"]

    # policy document now has a new active version with the updated hash
    policy_after = main.get_document(policy_id, include_html=True)
    assert "24 hours" in policy_after["html"]

    # the reference should now be STALE, with an OUTDATED_REFERENCE finding
    refs_after = main.list_references(workspace_id)
    assert refs_after[0]["status"] == models.ReferenceStatus.STALE
    findings_after = main.list_findings(workspace_id, status=models.FindingStatus.OPEN)
    assert any(f["reference_id"] == reference_id for f in findings_after)

    # -- 8. approve the propagated procedure change --------------------------
    durable_proc_id = proc_resp["document"]["superdocs_document_id"]
    fake_client.html[durable_proc_id] = PROCEDURE_HTML_UPDATED

    approve_proc_resp = main.approve_proposed_change(proc_pc_id, main.ApproveRequest(approved=True))
    assert approve_proc_resp["proposed_change"]["status"] == models.ProposedChangeStatus.APPROVED

    refs_final = main.list_references(workspace_id)
    assert refs_final[0]["status"] == models.ReferenceStatus.VALID

    findings_final = main.list_findings(workspace_id, status=models.FindingStatus.OPEN)
    assert not any(f["reference_id"] == reference_id for f in findings_final)

    ur = main.get_document(policy_id)  # sanity: still resolvable
    assert ur["id"] == policy_id

    # -- 9. report + export ---------------------------------------------------
    report = main.generate_report(workspace_id)
    assert report["summary"]["references_valid"] == 1
    assert report["summary"]["findings_open"] == 0

    export_resp = main.export_document(policy_id, fmt="docx")
    assert export_resp.body == b"FAKE-EXPORT-BYTES"

    events = main.list_change_events(workspace_id)
    event_types = {e["event_type"] for e in events}
    assert models.ChangeEventType.WORKSPACE_CREATED in event_types
    assert models.ChangeEventType.DOCUMENT_UPLOADED in event_types
    assert models.ChangeEventType.ANALYSIS_RUN_COMPLETED in event_types
    assert models.ChangeEventType.POLICY_EDIT_APPROVED in event_types
    assert models.ChangeEventType.PROCEDURE_CHANGE_APPROVED in event_types


def test_reject_policy_change_blocks_propagation(fake_client, fake_llm):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="Org", pack_name="Pack"))
    workspace_id = ws["id"]

    policy_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(filename="p.html", file_base64=_b64(POLICY_HTML_V1), doc_type="policy", title="Policy"),
    )
    policy_id = policy_resp["document"]["id"]
    proc_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(
            filename="pr.html", file_base64=_b64(PROCEDURE_HTML), doc_type="procedure", title="Procedure",
            parent_policy_id=policy_id,
        ),
    )
    proc_id = proc_resp["document"]["id"]

    policy_sections = main.get_document(policy_id)["sections"]
    proc_sections = main.get_document(proc_id)["sections"]
    breach_id = next(s["id"] for s in policy_sections if s["title"] == "Breach Notification")
    reporting_id = next(s["id"] for s in proc_sections if s["title"] == "Reporting Steps")
    fake_llm.set_canned("Policy", "Procedure", [(reporting_id, breach_id, 0.9, "match")])
    main.analyze_references(workspace_id)

    fake_client.queue_job_result(
        {
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {"change_id": "c1", "chunk_id": "p2", "old_html": "old", "new_html": "new", "ai_explanation": "x"}
                ]
            },
        }
    )
    ur_resp = main.create_update_request(policy_id, main.UpdateRequestCreate(instruction="change it"))
    pc_id = ur_resp["proposed_change"]["id"]

    resp = main.approve_proposed_change(pc_id, main.ApproveRequest(approved=False, feedback="not needed"))
    assert resp["proposed_change"]["status"] == models.ProposedChangeStatus.REJECTED
    assert resp["propagated"] == []

    # reference untouched -- still VALID, no propagation happened
    refs = main.list_references(workspace_id)
    assert refs[0]["status"] == models.ReferenceStatus.VALID


def test_low_confidence_reference_needs_review(fake_client, fake_llm):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="Org", pack_name="Pack"))
    workspace_id = ws["id"]
    policy_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(filename="p.html", file_base64=_b64(POLICY_HTML_V1), doc_type="policy", title="Policy"),
    )
    policy_id = policy_resp["document"]["id"]
    proc_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(
            filename="pr.html", file_base64=_b64(PROCEDURE_HTML), doc_type="procedure", title="Procedure",
            parent_policy_id=policy_id,
        ),
    )
    proc_id = proc_resp["document"]["id"]

    policy_sections = main.get_document(policy_id)["sections"]
    proc_sections = main.get_document(proc_id)["sections"]
    access_id = next(s["id"] for s in policy_sections if s["title"] == "Access Control")
    reporting_id = next(s["id"] for s in proc_sections if s["title"] == "Reporting Steps")

    fake_llm.set_canned("Policy", "Procedure", [(reporting_id, access_id, 0.6, "weak guess")])
    main.analyze_references(workspace_id)

    refs = main.list_references(workspace_id)
    assert refs[0]["status"] == models.ReferenceStatus.NEEDS_REVIEW

    ws_after = main.get_workspace(workspace_id)
    assert ws_after["status"] == models.WorkspaceStatus.NEEDS_ATTENTION

    validation = main.validate_workspace(workspace_id)
    assert validation["overall_status"] == "fail"  # LOW_CONFIDENCE_UNREVIEWED check fails


def test_real_superdocs_per_element_chunking_groups_body_into_section(fake_client, fake_llm):
    """
    Regression test for the bug found against a live SuperDocs response:
    a real parse of an uploaded .docx chunks per ELEMENT -- one
    data-chunk-id per paragraph, heading, table -- as flat top-level
    siblings, NOT one chunk per whole section the way this project's own
    hand-authored HTML (used by every other fixture in this file) wraps
    a heading plus its body together in one <div data-chunk-id>. Without
    grouping, every body paragraph was silently discarded and a section's
    stored content was just its bare heading text (confirmed live: the
    Preview panel showed the heading repeated as its own "content").

    This exercises that real shape end to end: upload discovers a section
    whose content includes the actual body text (not just the heading),
    and -- the part that would silently break change propagation -- a
    proposed change SuperDocs reports against a BODY chunk id (not the
    section's representative heading chunk id) still resolves back to the
    right section via SectionSnapshotChunk.
    """
    policy_html = (
        '<h2 data-chunk-id="hp1">Access Control</h2>'
        '<p data-chunk-id="bp1">Provision access within 5 business days of approval.</p>'
        '<h2 data-chunk-id="hp2">Breach Notification</h2>'
        '<p data-chunk-id="bp2">Report breaches within 60 hours of discovery.</p>'
    )
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="Org", pack_name="Pack"))
    workspace_id = ws["id"]
    policy_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(filename="p.html", file_base64=_b64(policy_html), doc_type="policy", title="Policy"),
    )
    policy_id = policy_resp["document"]["id"]
    sections = policy_resp["sections"]
    assert len(sections) == 2  # the two headings, NOT the four raw chunks

    breach = next(s for s in sections if s["title"] == "Breach Notification")
    # The bug: content_html used to equal the bare heading text ("Breach
    # Notification"). It must now contain the real body paragraph.
    assert "60 hours" in breach["content_html"]
    assert breach["content_html"] != breach["title"]

    # Regression guard for _enrich_pending_change: SuperDocs reports the
    # BODY chunk id it actually edited (bp2), not the heading chunk (hp2).
    fake_client.queue_job_result(
        {
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {
                        "change_id": "chg-1",
                        "chunk_id": "bp2",  # body chunk, not the heading chunk hp2
                        "old_html": "<p>Report breaches within 60 hours of discovery.</p>",
                        "new_html": "<p>Report breaches within 24 hours of discovery.</p>",
                        "ai_explanation": "Tightened the window.",
                    }
                ]
            },
        }
    )
    ur_resp = main.create_update_request(policy_id, main.UpdateRequestCreate(instruction="Tighten to 24 hours"))
    pc_id = ur_resp["proposed_change"]["id"]

    pending = main.list_proposed_changes(workspace_id, status="pending")
    pc = next(p for p in pending if p["id"] == pc_id)
    assert pc["section_id"] == breach["id"]  # resolved via the body chunk id, not the heading's


def test_missing_reference_flagged_by_validator(fake_client, fake_llm):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="Org", pack_name="Pack"))
    workspace_id = ws["id"]
    policy_resp = main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(filename="p.html", file_base64=_b64(POLICY_HTML_V1), doc_type="policy", title="Policy"),
    )
    policy_id = policy_resp["document"]["id"]
    main.upload_document(
        workspace_id,
        main.DocumentUploadRequest(
            filename="pr.html", file_base64=_b64(PROCEDURE_HTML), doc_type="procedure", title="Procedure",
            parent_policy_id=policy_id,
        ),
    )
    # No analyze_references call -- procedure has zero references.
    validation = main.validate_workspace(workspace_id)
    assert validation["overall_status"] == "fail"
    findings = main.list_findings(workspace_id)
    assert any(f["finding_type"] == models.FindingType.MISSING_REFERENCE for f in findings)
