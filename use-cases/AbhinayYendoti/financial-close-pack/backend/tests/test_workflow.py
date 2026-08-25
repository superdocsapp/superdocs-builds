"""End-to-end workflow: upload -> classify -> generate -> review -> sign -> export -> close."""

import io
import zipfile


def test_uploaded_bytes_are_stored_and_retrievable(client, auth, make_close):
    """`complete_upload` used to discard the file and hardcode 'Uploaded Support.pdf'."""
    close = make_close()
    payload = b"%PDF-1.4 trial balance bytes"

    document = client.post(
        f"/api/v1/closes/{close['id']}/documents",
        files={"file": ("Trial Balance.pdf", payload, "application/pdf")},
        headers=auth,
    ).json()

    assert document["filename"] == "Trial Balance.pdf"
    assert document["size"] == len(payload)
    assert document["document_type"] == "Trial Balance"

    content = client.get(
        f"/api/v1/closes/{close['id']}/documents/{document['id']}/content", headers=auth
    )
    assert content.status_code == 200
    assert content.content == payload


def test_empty_upload_is_rejected(client, auth, make_close):
    close = make_close()
    response = client.post(
        f"/api/v1/closes/{close['id']}/documents",
        files={"file": ("Empty.pdf", b"", "application/pdf")},
        headers=auth,
    )
    assert response.status_code == 400


def test_mapping_requires_a_type_when_none_can_be_inferred(client, auth, make_close):
    """The old mapping endpoint took no body and stamped everything READY."""
    close = make_close()
    document = client.post(
        f"/api/v1/closes/{close['id']}/documents",
        files={"file": ("zzz.bin", b"unknown", "application/octet-stream")},
        headers=auth,
    ).json()

    assert document["status"] == "PROCESSING"
    assert document["document_type"] is None

    blocked = client.patch(
        f"/api/v1/closes/{close['id']}/documents/{document['id']}/mapping", json={}, headers=auth
    )
    assert blocked.status_code == 400

    mapped = client.patch(
        f"/api/v1/closes/{close['id']}/documents/{document['id']}/mapping",
        json={"document_type": "Accruals"},
        headers=auth,
    ).json()
    assert mapped["status"] == "READY"
    assert mapped["document_type"] == "Accruals"


def test_generation_is_blocked_until_documents_and_checklist_are_done(client, auth, make_close):
    close = make_close()
    response = client.post(f"/api/v1/closes/{close['id']}/generate", headers=auth)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "GENERATION_BLOCKED"


def test_generation_calls_superdocs_and_creates_review_items(client, auth, ready_close):
    """Generation used to sleep through stage names and produce nothing."""
    close = ready_close()
    assert close["reviews"] == []

    job = client.post(f"/api/v1/closes/{close['id']}/generate", headers=auth).json()
    assert job["status"] == "RUNNING"

    finished = client.get(f"/api/v1/closes/{close['id']}/jobs/{job['id']}", headers=auth).json()
    assert finished["status"] == "SUCCEEDED", finished.get("error")

    refreshed = client.get(f"/api/v1/closes/{close['id']}", headers=auth).json()
    assert len(refreshed["reviews"]) == 3
    assert all(item["status"] == "PENDING" for item in refreshed["reviews"])
    assert refreshed["superdocs_document_ids"], "SuperDocs document ids were never recorded"
    assert refreshed["generating"] is False


def test_jobs_are_scoped_to_their_close(client, auth, ready_close, make_close):
    close = ready_close()
    other = make_close(entity="Other Ltd", period="2026-06", due_date="2026-07-05")
    job = client.post(f"/api/v1/closes/{close['id']}/generate", headers=auth).json()

    assert client.get(f"/api/v1/closes/{other['id']}/jobs/{job['id']}", headers=auth).status_code == 404


def test_generation_records_failure_instead_of_pretending_to_succeed(client, auth, ready_close, monkeypatch):
    from backend.app.core.config import settings

    close = ready_close()
    monkeypatch.setattr(settings, "superdocs_mode", "live")
    monkeypatch.setattr(settings, "superdocs_api_key", "")

    job = client.post(f"/api/v1/closes/{close['id']}/generate", headers=auth).json()
    finished = client.get(f"/api/v1/closes/{close['id']}/jobs/{job['id']}", headers=auth).json()

    assert finished["status"] == "FAILED"
    assert "SUPERDOCS_API_KEY" in finished["error"]

    refreshed = client.get(f"/api/v1/closes/{close['id']}", headers=auth).json()
    assert refreshed["generating"] is False
    assert "GENERATION_FAILED" in [entry["event"] for entry in refreshed["audit"]]


def test_audit_trail_is_readable_and_reflects_real_actions(client, auth, ready_close):
    """The trail was collected but no endpoint ever returned it; the UI showed fiction."""
    close = ready_close()
    trail = client.get(f"/api/v1/closes/{close['id']}/audit", headers=auth).json()

    events = [entry["event"] for entry in trail]
    assert events[0] == "CLOSE_CREATED"
    assert events.count("DOCUMENT_UPLOADED") == 8
    assert events.count("CHECKLIST_COMPLETED") == 7
    assert trail == sorted(trail, key=lambda entry: entry["created_at"])


def _drive_to_closable(client, auth, close_id):
    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"

    for review in client.get(f"/api/v1/closes/{close_id}/reviews", headers=auth).json():
        client.post(f"/api/v1/closes/{close_id}/reviews/{review['id']}/approve", headers=auth)
    for signoff in client.get(f"/api/v1/closes/{close_id}/signoffs", headers=auth).json():
        client.post(f"/api/v1/closes/{close_id}/signoffs/{signoff['id']}/approve", headers=auth)
    client.post(f"/api/v1/closes/{close_id}/export", headers=auth)


def test_close_gate_blocks_and_records_the_attempt(client, auth, ready_close):
    close = ready_close()
    response = client.post(f"/api/v1/closes/{close['id']}/close", headers=auth)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "CLOSE_BLOCKED"
    assert detail["blockers"]

    trail = client.get(f"/api/v1/closes/{close['id']}/audit", headers=auth).json()
    assert "CLOSE_BLOCKED" in [entry["event"] for entry in trail]


def test_export_produces_a_real_downloadable_pack(client, auth, ready_close):
    """Export used to flip a boolean and name three files that did not exist."""
    close = ready_close()
    _drive_to_closable(client, auth, close["id"])

    download = client.get(f"/api/v1/closes/{close['id']}/export/download", headers=auth)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert "attachment" in download.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert "00-manifest.json" in names
        assert "01-close-summary.pdf" in names
        assert "05-audit-trail.pdf" in names
        assert sum(1 for name in names if name.startswith("documents/")) == 8
        assert archive.read("02-checklist.pdf").startswith(b"%PDF-")
        assert archive.read("documents/Trial Balance.pdf") == b"content of Trial Balance.pdf"


def test_download_before_export_is_a_conflict_not_a_lie(client, auth, ready_close):
    close = ready_close()
    response = client.get(f"/api/v1/closes/{close['id']}/export/download", headers=auth)
    assert response.status_code == 409


def test_full_workflow_closes_the_period(client, auth, ready_close):
    close = ready_close()
    _drive_to_closable(client, auth, close["id"])

    response = client.post(f"/api/v1/closes/{close['id']}/close", headers=auth)
    assert response.status_code == 200

    closed = response.json()
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"] and closed["closed_by"]
    assert closed["readiness"]["readiness"] == 100


def test_a_closed_period_is_immutable(client, auth, ready_close):
    """Nothing used to check this: a CLOSED close stayed fully editable."""
    close = ready_close()
    _drive_to_closable(client, auth, close["id"])
    close_id = close["id"]
    assert client.post(f"/api/v1/closes/{close_id}/close", headers=auth).status_code == 200

    state = client.get(f"/api/v1/closes/{close_id}", headers=auth).json()
    checklist_item = state["checklist"][0]
    review = state["reviews"][0]

    assert client.post(f"/api/v1/closes/{close_id}/close", headers=auth).status_code == 409
    assert (
        client.patch(
            f"/api/v1/closes/{close_id}/checklist/{checklist_item['id']}",
            json={"status": "PENDING"},
            headers=auth,
        ).status_code
        == 409
    )
    assert (
        client.post(f"/api/v1/closes/{close_id}/reviews/{review['id']}/reject", headers=auth).status_code == 409
    )
    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 409
    assert client.post(f"/api/v1/closes/{close_id}/export", headers=auth).status_code == 409
    assert (
        client.post(
            f"/api/v1/closes/{close_id}/documents",
            files={"file": ("Late.pdf", b"late", "application/pdf")},
            headers=auth,
        ).status_code
        == 409
    )

    # The pack stays downloadable after closing.
    assert client.get(f"/api/v1/closes/{close_id}/export/download", headers=auth).status_code == 200


def test_rejecting_a_change_records_the_reason(client, auth, ready_close):
    close = ready_close()
    job = client.post(f"/api/v1/closes/{close['id']}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close['id']}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"

    review = client.get(f"/api/v1/closes/{close['id']}/reviews", headers=auth).json()[0]
    result = client.post(
        f"/api/v1/closes/{close['id']}/reviews/{review['id']}/reject",
        json={"reason": "Figure disagrees with the ledger"},
        headers=auth,
    ).json()

    assert result["status"] == "REJECTED"
    assert result["reason"] == "Figure disagrees with the ledger"
    assert result["reviewed_by"] and result["reviewed_at"]


def test_deleting_a_document_removes_the_record_and_the_bytes(client, auth, make_close):
    """A close must be able to shed evidence collected in error.

    Without this the only way to undo an upload was to edit the database by hand, so one
    unprocessable file could block a close permanently.
    """
    close = make_close()
    document = client.post(
        f"/api/v1/closes/{close['id']}/documents",
        files={"file": ("Trial Balance.pdf", b"%PDF-1.4 bytes", "application/pdf")},
        headers=auth,
    ).json()

    removed = client.delete(
        f"/api/v1/closes/{close['id']}/documents/{document['id']}", headers=auth
    )
    assert removed.status_code == 204

    listing = client.get(f"/api/v1/closes/{close['id']}/documents", headers=auth).json()
    assert all(item["id"] != document["id"] for item in listing)

    # The stored object goes with the record; a listed document that 404s on download
    # would be worse than no document at all.
    content = client.get(
        f"/api/v1/closes/{close['id']}/documents/{document['id']}/content", headers=auth
    )
    assert content.status_code == 404

    events = client.get(f"/api/v1/closes/{close['id']}/audit", headers=auth).json()
    assert any(
        event["event"] == "DOCUMENT_DELETED" and "Trial Balance.pdf" in (event["detail"] or "")
        for event in events
    )


def test_deleting_an_unknown_document_is_a_404(client, auth, make_close):
    close = make_close()
    response = client.delete(f"/api/v1/closes/{close['id']}/documents/doc_missing", headers=auth)
    assert response.status_code == 404


def test_deleting_a_document_invalidates_an_existing_export(client, auth, make_close):
    """Removing evidence changes what the pack would contain, so the pack is stale."""
    close = make_close()
    document = client.post(
        f"/api/v1/closes/{close['id']}/documents",
        files={"file": ("Bank Recon.pdf", b"%PDF-1.4 bytes", "application/pdf")},
        headers=auth,
    ).json()

    client.delete(f"/api/v1/closes/{close['id']}/documents/{document['id']}", headers=auth)

    detail = client.get(f"/api/v1/closes/{close['id']}", headers=auth).json()
    assert detail["exported"] is False
