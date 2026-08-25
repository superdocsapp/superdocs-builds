"""The SuperDocs contract, end to end.

    upload_document -> send_edit_instruction -> approve_changes -> export_document

Before this suite the app exercised only the first two: approvals were recorded locally
and the export was an app-built zip that SuperDocs never saw. These tests pin the whole
sequence, including the failure paths, so a passing run is evidence the contract is
actually driven rather than described.
"""

import io
import json
import zipfile

import pytest

from backend.app.core.config import settings
from backend.app.db import store
from backend.app.integrations.superdocs import client as superdocs_client
from backend.app.integrations.superdocs.client import CONTRACT_OPERATIONS
from backend.app.services.memo import SUPPORTING_MEMO_NAME

CLOSE = "/api/v1/closes"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def generate(client, auth, close_id):
    job = client.post(f"{CLOSE}/{close_id}/generate", headers=auth).json()
    status = client.get(f"{CLOSE}/{close_id}/jobs/{job['id']}", headers=auth).json()
    assert status["status"] == "SUCCEEDED", status.get("error")
    return status


def decide_all(client, auth, close_id, *, reject_first=False, decisions=None):
    """Decide every proposed change.

    SuperDocs reviews a batch as a unit - the top-level `approved` is the default for any
    change the request does not name - so deciding item by item completed the job on the
    first call and made every later one fail with 400. Decisions are recorded locally and
    the whole batch is transmitted once, when the last one is made.
    """
    reviews = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
    verdicts = decisions or {}
    for index, review in enumerate(reviews):
        verb = verdicts.get(review["id"], "reject" if reject_first and index == 0 else "approve")
        if verb == "reject":
            response = client.post(
                f"{CLOSE}/{close_id}/reviews/{review['id']}/reject",
                json={"reason": "restated by the controller"},
                headers=auth,
            )
        else:
            response = client.post(f"{CLOSE}/{close_id}/reviews/{review['id']}/approve", headers=auth)
        assert response.status_code == 200, response.text
    return reviews


def sign_all(client, auth, close_id):
    for signoff in client.get(f"{CLOSE}/{close_id}/signoffs", headers=auth).json():
        if signoff["status"] != "APPROVED":
            assert client.post(f"{CLOSE}/{close_id}/signoffs/{signoff['id']}/approve", headers=auth).status_code == 200


def ledger(client, auth, close_id):
    return client.get(f"{CLOSE}/{close_id}/superdocs", headers=auth).json()


def operations(client, auth, close_id, name):
    return [entry for entry in ledger(client, auth, close_id)["operations"] if entry["operation"] == name]


def open_pack(client, auth, close_id):
    download = client.get(f"{CLOSE}/{close_id}/export/download", headers=auth)
    assert download.status_code == 200, download.text
    return zipfile.ZipFile(io.BytesIO(download.content))


class Failing:
    """An adapter that fails one operation and behaves normally for the rest."""

    def __init__(self, failing_operation: str) -> None:
        self.inner = superdocs_client.MockSuperDocsClient()
        self.failing_operation = failing_operation

    async def upload_document(self, filename, content):
        if self.failing_operation == "upload_document":
            raise superdocs_client.SuperDocsResponseError("SuperDocs upload is unavailable")
        return await self.inner.upload_document(filename, content)

    async def edit_document(self, document_id, instruction, document_html=None):
        return await self.inner.edit_document(document_id, instruction, document_html)

    async def approve_changes(self, document_id, change_ids, rejected_change_ids=None):
        if self.failing_operation == "approve_changes":
            raise superdocs_client.SuperDocsResponseError("SuperDocs returned 503 for POST /approve")
        return await self.inner.approve_changes(document_id, change_ids, rejected_change_ids)

    async def export_document(self, document_id, approved_change_ids=None):
        if self.failing_operation == "export_document":
            raise superdocs_client.SuperDocsResponseError("SuperDocs returned 500 for POST /export")
        return await self.inner.export_document(document_id, approved_change_ids)


@pytest.fixture
def break_superdocs(monkeypatch):
    """Swap the adapter at both call sites so one operation fails."""

    def _break(operation: str):
        broken = Failing(operation)
        monkeypatch.setattr("backend.app.api.routes.get_client", lambda: broken)
        monkeypatch.setattr("backend.app.services.generation.get_client", lambda: broken)
        return broken

    return _break


# --------------------------------------------------------------------------------------
# approve_changes
# --------------------------------------------------------------------------------------


def test_deciding_the_batch_calls_superdocs_approve_once(client, auth, ready_close):
    """The decision used to be purely local; SuperDocs never heard about it."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    reviews = decide_all(client, auth, close_id)

    after = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
    assert {item["status"] for item in after} == {"APPROVED"}
    receipt = after[0]["superdocs_approval"]
    assert receipt["document_id"]
    assert sorted(receipt["approved_change_ids"]) == sorted(item["external_change_id"] for item in reviews)

    # One call for the batch, not one per click.
    calls = operations(client, auth, close_id, "approve_changes")
    assert len(calls) == 1
    assert calls[0]["status"] == "SUCCEEDED"
    assert calls[0]["request_id"]


def test_no_superdocs_call_until_every_change_is_decided(client, auth, ready_close):
    """A partly decided batch must not be submitted: the remainder would be resolved
    by default, which is precisely the bug that lost rejections."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    reviews = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
    assert len(reviews) > 1

    client.post(f"{CLOSE}/{close_id}/reviews/{reviews[0]['id']}/approve", headers=auth)

    assert operations(client, auth, close_id, "approve_changes") == []


def test_a_rejected_change_is_transmitted_as_a_rejection(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    reviews = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
    rejected = reviews[0]

    decide_all(client, auth, close_id, decisions={rejected["id"]: "reject"})

    calls = operations(client, auth, close_id, "approve_changes")
    assert len(calls) == 1
    # The rejected change is never in the approved set.
    assert rejected["external_change_id"] not in calls[0]["change_ids"]

    after = next(
        item for item in client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
        if item["id"] == rejected["id"]
    )
    assert after["status"] == "REJECTED"
    assert after["superdocs_approval"] is None


def test_superdocs_batch_failure_keeps_the_reviewer_decisions(client, auth, ready_close, break_superdocs):
    """The decisions belong to the reviewer, not to SuperDocs.

    Discarding them on a transport failure would make the reviewer decide everything
    again; the export retries the submission instead.
    """
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    break_superdocs("approve_changes")

    decide_all(client, auth, close_id)

    after = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
    assert {item["status"] for item in after} == {"APPROVED"}
    # No receipt is invented for a call that failed.
    assert all(item["superdocs_approval"] is None for item in after)


def test_a_failed_batch_is_recorded_in_the_ledger_and_audit(client, auth, ready_close, break_superdocs):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    break_superdocs("approve_changes")

    decide_all(client, auth, close_id)

    calls = operations(client, auth, close_id, "approve_changes")
    assert [call["status"] for call in calls] == ["FAILED"]
    assert "503" in calls[0]["error"]

    trail = [entry["event"] for entry in client.get(f"{CLOSE}/{close_id}/audit", headers=auth).json()]
    assert "REVIEW_APPROVAL_FAILED" in trail


def test_a_failed_approval_leaves_the_close_gate_shut(client, auth, ready_close, break_superdocs):
    """A false local success would have let the period close on an unapproved change."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    sign_all(client, auth, close_id)
    break_superdocs("approve_changes")

    for review in client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json():
        client.post(f"{CLOSE}/{close_id}/reviews/{review['id']}/approve", headers=auth)

    assert client.post(f"{CLOSE}/{close_id}/close", headers=auth).status_code == 409


def test_rejecting_a_change_does_not_call_superdocs_approve(client, auth, ready_close):
    """Only approvals are sent; a rejected change must never reach the export."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    review = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()[0]

    rejected = client.post(
        f"{CLOSE}/{close_id}/reviews/{review['id']}/reject", json={"reason": "not supported"}, headers=auth
    ).json()

    assert rejected["status"] == "REJECTED"
    assert rejected["superdocs_approval"] is None
    assert operations(client, auth, close_id, "approve_changes") == []


def test_approval_requires_generation_first(client, auth, ready_close):
    """There is no working document to approve against before the edit round."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    review = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()[0]

    def clear(close):
        close["superdocs_working_document_id"] = None

    store.mutate_close(close_id, clear)

    response = client.post(f"{CLOSE}/{close_id}/reviews/{review['id']}/approve", headers=auth)
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "NOT_GENERATED"


# --------------------------------------------------------------------------------------
# export_document
# --------------------------------------------------------------------------------------


def test_export_calls_superdocs_export_with_the_approved_changes(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    reviews = decide_all(client, auth, close_id, reject_first=True)
    sign_all(client, auth, close_id)

    result = client.post(f"{CLOSE}/{close_id}/export", headers=auth).json()

    superdocs_export = result["superdocs_export"]
    assert superdocs_export["kind"] == "SUPERDOCS_EXPORT"
    assert superdocs_export["size"] > 0
    # The rejected change must not be in the exported document.
    assert reviews[0]["external_change_id"] not in superdocs_export["approved_change_ids"]
    assert sorted(superdocs_export["approved_change_ids"]) == sorted(
        review["external_change_id"] for review in reviews[1:]
    )

    calls = operations(client, auth, close_id, "export_document")
    assert len(calls) == 1 and calls[0]["status"] == "SUCCEEDED"


def test_export_distinguishes_the_superdocs_document_from_the_app_zip(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    result = client.post(f"{CLOSE}/{close_id}/export", headers=auth).json()

    assert result["kind"] == "APP_ZIP"
    assert result["filename"].endswith(".zip")
    assert result["superdocs_export"]["kind"] == "SUPERDOCS_EXPORT"
    assert result["superdocs_export"]["filename"] != result["filename"]

    status = client.get(f"{CLOSE}/{close_id}/export", headers=auth).json()
    assert status["export"]["kind"] == "APP_ZIP"
    assert status["superdocs_export"]["kind"] == "SUPERDOCS_EXPORT"


def test_exported_zip_carries_the_superdocs_document_and_metadata(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    superdocs_export = client.post(f"{CLOSE}/{close_id}/export", headers=auth).json()["superdocs_export"]

    with open_pack(client, auth, close_id) as archive:
        names = archive.namelist()
        assert f"superdocs/{superdocs_export['filename']}" in names
        assert archive.read(f"superdocs/{superdocs_export['filename']}").startswith(b"%PDF-")

        metadata = json.loads(archive.read("superdocs/export-metadata.json"))
        assert metadata["document_id"] == superdocs_export["document_id"]
        assert metadata["export_id"] == superdocs_export["export_id"]

        recorded = json.loads(archive.read("superdocs/operation-ledger.json"))
        assert recorded["coverage"]["complete"] is True
        assert {entry["operation"] for entry in recorded["operations"]} == set(CONTRACT_OPERATIONS)


def test_manifest_records_contract_coverage(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    with open_pack(client, auth, close_id) as archive:
        manifest = json.loads(archive.read("00-manifest.json"))

    assert manifest["superdocs"]["mode"] == "mock"
    assert manifest["superdocs"]["working_document_id"]
    assert manifest["superdocs"]["contract_coverage"]["complete"] is True
    assert manifest["superdocs"]["export"]["kind"] == "SUPERDOCS_EXPORT"


def test_superdocs_export_failure_exports_nothing(client, auth, ready_close, break_superdocs):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    break_superdocs("export_document")

    response = client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "SUPERDOCS_EXPORT_FAILED"

    status = client.get(f"{CLOSE}/{close_id}/export", headers=auth).json()
    assert status["exported"] is False
    assert status["superdocs_export"] is None
    assert client.get(f"{CLOSE}/{close_id}/export/download", headers=auth).status_code == 409
    assert client.post(f"{CLOSE}/{close_id}/close", headers=auth).status_code == 409

    calls = operations(client, auth, close_id, "export_document")
    assert [call["status"] for call in calls] == ["FAILED"]


def test_export_requires_generation_first(client, auth, ready_close):
    close_id = ready_close()["id"]
    response = client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "NOT_GENERATED"


# --------------------------------------------------------------------------------------
# Supporting Memo
# --------------------------------------------------------------------------------------


def test_supporting_memo_is_generated_as_a_first_class_artifact(client, auth, ready_close):
    close_id = ready_close()["id"]
    assert client.get(f"{CLOSE}/{close_id}/artifacts", headers=auth).json() == []

    generate(client, auth, close_id)

    artifacts = client.get(f"{CLOSE}/{close_id}/artifacts", headers=auth).json()
    memo = next(item for item in artifacts if item["name"] == SUPPORTING_MEMO_NAME)
    assert memo["kind"] == "SUPPORTING_MEMO"
    assert memo["size"] > 0 and memo["sha256"]

    content = client.get(f"{CLOSE}/{close_id}/artifacts/{memo['id']}/content", headers=auth)
    assert content.status_code == 200
    assert content.content.startswith(b"%PDF-")
    assert SUPPORTING_MEMO_NAME in content.headers["content-disposition"]


def test_supporting_memo_summarises_the_uploaded_evidence(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    memo = client.get(f"{CLOSE}/{close_id}/artifacts", headers=auth).json()[0]
    body = client.get(f"{CLOSE}/{close_id}/artifacts/{memo['id']}/content", headers=auth).content.decode("latin-1")

    assert "Supporting Memo" in body
    assert "SOURCE EVIDENCE" in body and "Trial Balance.pdf" in body
    assert "CHECKLIST" in body
    assert "SUPERDOCS PROPOSED CHANGES" in body and "Revenue Summary" in body
    assert "SIGN-OFFS" in body


def test_supporting_memo_is_included_in_the_export(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    with open_pack(client, auth, close_id) as archive:
        assert SUPPORTING_MEMO_NAME in archive.namelist()
        assert archive.read(SUPPORTING_MEMO_NAME).startswith(b"%PDF-")
        manifest = json.loads(archive.read("00-manifest.json"))

    assert any(item["name"] == SUPPORTING_MEMO_NAME for item in manifest["generated_artifacts"])


def test_the_packaged_memo_reflects_decisions_made_after_generation(client, auth, ready_close):
    """Generated at generation time, rebuilt at export time so it is never stale."""
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id, reject_first=True)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    with open_pack(client, auth, close_id) as archive:
        packaged = archive.read(SUPPORTING_MEMO_NAME).decode("latin-1")

    assert "[REJECTED]" in packaged
    assert "restated by the controller" in packaged


# --------------------------------------------------------------------------------------
# Operation ledger
# --------------------------------------------------------------------------------------


def test_the_ledger_records_all_four_contract_operations(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    recorded = ledger(client, auth, close_id)

    assert recorded["coverage"]["complete"] is True
    assert {entry["operation"] for entry in recorded["operations"]} == set(CONTRACT_OPERATIONS)
    assert [item["operation"] for item in recorded["coverage"]["operations"]] == list(CONTRACT_OPERATIONS)


def test_ledger_entries_carry_the_required_fields(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)

    for entry in ledger(client, auth, close_id)["operations"]:
        assert entry["operation"] in CONTRACT_OPERATIONS
        assert entry["mode"] == "mock"
        assert entry["status"] in {"SUCCEEDED", "FAILED"}
        assert entry["started_at"] and entry["completed_at"]
        assert isinstance(entry["duration_ms"], int)
        assert "error" in entry and "request_id" in entry and "document_id" in entry


def test_the_ledger_records_operations_in_contract_order(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    sequence = [entry["operation"] for entry in ledger(client, auth, close_id)["operations"]]
    first_seen = [name for index, name in enumerate(sequence) if name not in sequence[:index]]

    assert first_seen == list(CONTRACT_OPERATIONS)


def test_the_ledger_is_scoped_to_its_close(client, auth, ready_close):
    first = ready_close()["id"]
    second = ready_close(period="2026-05")["id"]
    generate(client, auth, first)

    assert ledger(client, auth, first)["operations"]
    assert ledger(client, auth, second)["operations"] == []


def test_the_ledger_survives_a_restart(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)

    before = len(ledger(client, auth, close_id)["operations"])
    reloaded = store.get_close(close_id)

    assert len(reloaded["superdocs_operations"]) == before


# --------------------------------------------------------------------------------------
# Mock determinism and secret hygiene
# --------------------------------------------------------------------------------------


def test_mock_mode_needs_no_api_key(client, auth, ready_close, monkeypatch):
    monkeypatch.setattr(settings, "superdocs_mode", "mock")
    monkeypatch.setattr(settings, "superdocs_api_key", "")

    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)

    assert client.post(f"{CLOSE}/{close_id}/export", headers=auth).status_code == 200
    assert ledger(client, auth, close_id)["coverage"]["complete"] is True


def test_mock_mode_is_deterministic(client, auth, ready_close):
    """Two identical closes must produce identical SuperDocs output."""
    results = []
    for period in ("2026-04", "2026-05"):
        close_id = ready_close(period=period)["id"]
        generate(client, auth, close_id)
        decide_all(client, auth, close_id)
        sign_all(client, auth, close_id)
        export = client.post(f"{CLOSE}/{close_id}/export", headers=auth).json()["superdocs_export"]
        reviews = client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).json()
        results.append(
            {
                "export_id": export["export_id"],
                "sha256": export["sha256"],
                "changes": [review["external_change_id"] for review in reviews],
                "receipts": [review["superdocs_approval"]["request_id"] for review in reviews],
            }
        )

    assert results[0] == results[1]


@pytest.mark.asyncio
async def test_mock_export_bytes_are_reproducible():
    mock = superdocs_client.MockSuperDocsClient()
    first = await mock.export_document("doc-1", ["change-a", "change-b"])
    second = await mock.export_document("doc-1", ["change-b", "change-a"])

    assert first["content_base64"] == second["content_base64"]
    assert first["sha256"] == second["sha256"]
    assert first["export_id"] == second["export_id"]


def test_live_mode_configuration_never_leaks_the_api_key(client, auth, ready_close, monkeypatch):
    """The key must not reach the ledger, the manifest, the API or the exported pack."""
    secret = "sk-live-must-never-appear-anywhere"
    monkeypatch.setattr(settings, "superdocs_api_key", secret)

    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    surfaces = [
        client.get(f"{CLOSE}/{close_id}/superdocs", headers=auth).text,
        client.get(f"{CLOSE}/{close_id}", headers=auth).text,
        client.get(f"{CLOSE}/{close_id}/export", headers=auth).text,
        client.get(f"{CLOSE}/{close_id}/reviews", headers=auth).text,
        client.get(f"{CLOSE}/{close_id}/audit", headers=auth).text,
        json.dumps(store.get_close(close_id)),
    ]
    with open_pack(client, auth, close_id) as archive:
        surfaces.extend(archive.read(name).decode("latin-1") for name in archive.namelist())

    for surface in surfaces:
        assert secret not in surface


def test_redaction_strips_credential_shaped_response_fields():
    from backend.app.services.superdocs_ops import redact

    cleaned = redact(
        {
            "document_id": "doc-1",
            "api_key": "sk-live-leak",
            "content_base64": "AAAA",
            "nested": [{"token": "t-leak", "safe": "keep"}],
        }
    )

    assert cleaned["document_id"] == "doc-1"
    assert "sk-live-leak" not in json.dumps(cleaned)
    assert "AAAA" not in json.dumps(cleaned)
    assert cleaned["nested"][0]["safe"] == "keep"


# --------------------------------------------------------------------------------------
# Gate and immutability, re-pinned against the new SuperDocs steps
# --------------------------------------------------------------------------------------


def test_close_is_blocked_until_signoffs_are_complete(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    decide_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)

    blocked = client.post(f"{CLOSE}/{close_id}/close", headers=auth)
    assert blocked.status_code == 409
    assert any("sign-off" in blocker for blocker in blocked.json()["detail"]["blockers"])

    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)
    assert client.post(f"{CLOSE}/{close_id}/close", headers=auth).status_code == 200


def test_a_closed_period_rejects_further_superdocs_operations(client, auth, ready_close):
    close_id = ready_close()["id"]
    generate(client, auth, close_id)
    reviews = decide_all(client, auth, close_id)
    sign_all(client, auth, close_id)
    client.post(f"{CLOSE}/{close_id}/export", headers=auth)
    assert client.post(f"{CLOSE}/{close_id}/close", headers=auth).status_code == 200

    before = len(ledger(client, auth, close_id)["operations"])

    assert client.post(f"{CLOSE}/{close_id}/reviews/{reviews[0]['id']}/approve", headers=auth).status_code == 409
    assert client.post(f"{CLOSE}/{close_id}/export", headers=auth).status_code == 409
    assert client.post(f"{CLOSE}/{close_id}/generate", headers=auth).status_code == 409

    assert len(ledger(client, auth, close_id)["operations"]) == before


def test_a_close_written_before_the_contract_is_backfilled(client, auth, ready_close):
    """An older database must not render half-populated, and its stale export cannot
    satisfy the gate: it was produced before SuperDocs was part of the flow."""
    from backend.app.services.demo import backfill_closes

    close_id = ready_close()["id"]

    def regress(close):
        for field in ("superdocs_working_document_id", "superdocs_export", "superdocs_operations", "generated_artifacts"):
            close.pop(field, None)
        close["exported"] = True
        close["export"] = {"filename": "legacy.zip", "storage_key": "legacy", "size": 1, "files": []}

    store.mutate_close(close_id, regress)

    backfill_closes()

    restored = store.get_close(close_id)
    assert restored["superdocs_operations"] == []
    assert restored["generated_artifacts"] == []
    assert restored["superdocs_working_document_id"] is None
    assert restored["exported"] is False and restored["export"] is None
    assert client.get(f"{CLOSE}/{close_id}/superdocs", headers=auth).status_code == 200
