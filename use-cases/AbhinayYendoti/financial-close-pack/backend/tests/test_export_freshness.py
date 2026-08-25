"""An exported pack must describe the close it is filed against.

`exported` used to be a sticky boolean. Once set, any later change - a document, a
review decision, a sign-off - left it true, so the close gate stayed satisfied by a zip
that predated the change and the period could be locked against it. The frontend made
it worse: its export button turned into "Download pack" and never offered a re-export.
"""

import io
import zipfile


def _drive_to_export(client, auth, close_id):
    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"
    for review in client.get(f"/api/v1/closes/{close_id}/reviews", headers=auth).json():
        client.post(f"/api/v1/closes/{close_id}/reviews/{review['id']}/approve", headers=auth)
    for signoff in client.get(f"/api/v1/closes/{close_id}/signoffs", headers=auth).json():
        client.post(f"/api/v1/closes/{close_id}/signoffs/{signoff['id']}/approve", headers=auth)
    assert client.post(f"/api/v1/closes/{close_id}/export", headers=auth).status_code == 200


def test_a_late_document_retires_the_exported_pack(client, auth, ready_close):
    """The pack was missing the late document, yet the gate still let the period close."""
    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)
    assert client.get(f"/api/v1/closes/{close_id}/readiness", headers=auth).json()["ready_for_close"] is True

    client.post(
        f"/api/v1/closes/{close_id}/documents",
        files={"file": ("Bank Reconciliation Addendum.pdf", b"late evidence", "application/pdf")},
        headers=auth,
    )

    readiness = client.get(f"/api/v1/closes/{close_id}/readiness", headers=auth).json()
    assert readiness["ready_for_close"] is False
    assert "Final pack export pending" in readiness["blockers"]

    response = client.post(f"/api/v1/closes/{close_id}/close", headers=auth)
    assert response.status_code == 409
    assert "Final pack export pending" in response.json()["detail"]["blockers"]


def test_the_retired_pack_is_no_longer_offered_for_download(client, auth, ready_close):
    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)

    client.post(
        f"/api/v1/closes/{close_id}/documents",
        files={"file": ("Bank Reconciliation Addendum.pdf", b"late evidence", "application/pdf")},
        headers=auth,
    )

    status = client.get(f"/api/v1/closes/{close_id}/export", headers=auth).json()
    assert status["exported"] is False
    assert status["export"] is None
    # 409 NOT_EXPORTED, so the UI shows "Export pack" again instead of a stale download.
    assert client.get(f"/api/v1/closes/{close_id}/export/download", headers=auth).status_code == 409

    trail = [entry["event"] for entry in client.get(f"/api/v1/closes/{close_id}/audit", headers=auth).json()]
    assert "EXPORT_INVALIDATED" in trail


def test_re_exporting_picks_up_the_change_and_reopens_the_gate(client, auth, ready_close):
    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)

    client.post(
        f"/api/v1/closes/{close_id}/documents",
        files={"file": ("Bank Reconciliation Addendum.pdf", b"late evidence", "application/pdf")},
        headers=auth,
    )
    assert client.post(f"/api/v1/closes/{close_id}/export", headers=auth).status_code == 200

    download = client.get(f"/api/v1/closes/{close_id}/export/download", headers=auth)
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert "documents/Bank Reconciliation Addendum.pdf" in archive.namelist()
        assert archive.read("documents/Bank Reconciliation Addendum.pdf") == b"late evidence"

    assert client.post(f"/api/v1/closes/{close_id}/close", headers=auth).status_code == 200


def test_every_kind_of_change_retires_the_pack(client, auth, ready_close):
    """Documents, checklist, reviews and sign-offs all alter what the pack contains."""

    def exported(close_id):
        return client.get(f"/api/v1/closes/{close_id}/export", headers=auth).json()["exported"]

    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)
    item = client.get(f"/api/v1/closes/{close_id}/checklist", headers=auth).json()[0]
    client.patch(f"/api/v1/closes/{close_id}/checklist/{item['id']}", json={"status": "PENDING"}, headers=auth)
    assert exported(close_id) is False

    close_id = ready_close(period="2026-05")["id"]
    _drive_to_export(client, auth, close_id)
    document = client.get(f"/api/v1/closes/{close_id}/documents", headers=auth).json()[0]
    client.patch(
        f"/api/v1/closes/{close_id}/documents/{document['id']}/mapping",
        json={"document_type": "Trial Balance"},
        headers=auth,
    )
    assert exported(close_id) is False

    close_id = ready_close(period="2026-06")["id"]
    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"
    reviews = client.get(f"/api/v1/closes/{close_id}/reviews", headers=auth).json()
    for review in reviews[1:]:
        client.post(f"/api/v1/closes/{close_id}/reviews/{review['id']}/approve", headers=auth)
    for signoff in client.get(f"/api/v1/closes/{close_id}/signoffs", headers=auth).json():
        client.post(f"/api/v1/closes/{close_id}/signoffs/{signoff['id']}/approve", headers=auth)
    # Export while one decision is outstanding, then make it.
    client.post(f"/api/v1/closes/{close_id}/export", headers=auth)
    client.post(f"/api/v1/closes/{close_id}/reviews/{reviews[0]['id']}/approve", headers=auth)
    assert exported(close_id) is False


def test_regenerating_retires_the_pack(client, auth, ready_close):
    """Generation rewrites the review queue, so an earlier pack describes a dead state."""
    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)

    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"

    assert client.get(f"/api/v1/closes/{close_id}/export", headers=auth).json()["exported"] is False


def test_closing_the_period_keeps_the_pack_downloadable(client, auth, ready_close):
    """Invalidation must not fire on closure itself, or the pack becomes unreachable."""
    close_id = ready_close()["id"]
    _drive_to_export(client, auth, close_id)
    assert client.post(f"/api/v1/closes/{close_id}/close", headers=auth).status_code == 200

    assert client.get(f"/api/v1/closes/{close_id}/export", headers=auth).json()["exported"] is True
    assert client.get(f"/api/v1/closes/{close_id}/export/download", headers=auth).status_code == 200
