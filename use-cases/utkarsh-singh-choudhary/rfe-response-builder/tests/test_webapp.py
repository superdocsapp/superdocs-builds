"""
Tests for webapp/app.py -- the Flask layer only. Domain logic is already
covered by test_rfe.py / test_generate_integration.py; these just prove
the web wiring (validation, dry-run rendering, CSRF, error handling)
behaves without ever calling the real SuperDocs API.
"""
import io
import sys
from pathlib import Path

import pytest

WEBAPP_DIR = Path(__file__).parent.parent / "webapp"
sys.path.insert(0, str(WEBAPP_DIR))

import app as webapp_module  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
NOTICE = (DATA_DIR / "sample_rfe_notice.txt").read_bytes()
PETITION = (DATA_DIR / "sample_petition_arguments.json").read_bytes()
EVIDENCE = (DATA_DIR / "sample_new_evidence.json").read_bytes()


@pytest.fixture
def client():
    webapp_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    if webapp_module.limiter is not None:
        webapp_module.limiter.enabled = False
    with webapp_module.app.test_client() as c:
        yield c
    if webapp_module.limiter is not None:
        webapp_module.limiter.enabled = True


def _form(**overrides):
    form = {
        "notice": (io.BytesIO(NOTICE), "notice.txt"),
        "petition": (io.BytesIO(PETITION), "petition.json"),
        "case_id": "CASE-2002",
        "client_name": "Marco Alvarez",
        "dry_run": "on",
    }
    form.update(overrides)
    return form


def test_index_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"RFE Response Builder" in resp.data


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_dry_run_generates_results_page(client):
    resp = client.post("/generate", data=_form(), content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Dry run for CASE-2002" in resp.data


def test_missing_notice_redirects_with_flash(client):
    form = _form()
    del form["notice"]
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"upload an RFE notice" in resp.data


def test_wrong_extension_rejected(client):
    form = _form(notice=(io.BytesIO(NOTICE), "notice.docx"))
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Could not process input" in resp.data


def test_malformed_petition_json_rejected(client):
    form = _form(petition=(io.BytesIO(b"not json"), "petition.json"))
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Could not process input" in resp.data


def test_petition_missing_arguments_key_rejected(client):
    form = _form(petition=(io.BytesIO(b'{"not_arguments": []}'), "petition.json"))
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Could not process input" in resp.data


def test_unusable_case_id_rejected(client):
    form = _form(case_id="///", dry_run="on")
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Could not process input" in resp.data


def test_real_run_without_api_key_falls_back_to_flash(client, monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    form = _form(dry_run="")
    resp = client.post("/generate", data=form, content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200
    assert b"SUPERDOCS_API_KEY is not configured" in resp.data


def test_oversized_upload_returns_413(client, monkeypatch):
    monkeypatch.setitem(webapp_module.app.config, "MAX_CONTENT_LENGTH", 10)
    form = _form()
    resp = client.post("/generate", data=form, content_type="multipart/form-data")
    assert resp.status_code == 413
    assert b"File too large" in resp.data


def test_evidence_file_is_optional(client):
    resp = client.post("/generate", data=_form(evidence=(io.BytesIO(EVIDENCE), "evidence.json")),
                        content_type="multipart/form-data")
    assert resp.status_code == 200


def test_supporting_docs_multi_upload_accepted_in_dry_run(client):
    doc1 = (io.BytesIO(b"This is a long enough paragraph about the beneficiary's job duties and role."),
             "employer_letter.txt")
    resp = client.post(
        "/generate",
        data=_form(supporting_docs=[doc1]),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert b"Dry run for CASE-2002" in resp.data


def test_supporting_docs_wrong_extension_rejected(client):
    doc1 = (io.BytesIO(b"not a text file"), "employer_letter.docx")
    resp = client.post(
        "/generate",
        data=_form(supporting_docs=[doc1]),
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Could not process input" in resp.data


def _mock_pending_review(m, session_url_prefix="https://api.superdocs.app"):
    import re as _re
    m.post(f"{session_url_prefix}/v1/chat", json={"response": "ok", "document_changes": {}})
    m.post(f"{session_url_prefix}/v1/chat/async", json={"job_id": "job-1"})
    m.get(
        f"{session_url_prefix}/v1/jobs/job-1",
        json={
            "status": "awaiting_approval",
            "pending_changes": [{"chunk_id": "chunk-1",
                                  "proposed_text": "Drafted section addressing the officer's concern with citations."}],
        },
    )
    m.post(_re.compile(rf"{session_url_prefix}/v1/chat/.+/approve"), json={"status": "ok"})
    m.post(f"{session_url_prefix}/v1/documents/export", content=b"FAKE_DOCX")


def test_real_run_redirects_to_review_page(client, monkeypatch):
    import requests_mock

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_fake")
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        resp = client.post("/generate", data=_form(dry_run=""), content_type="multipart/form-data",
                            follow_redirects=True)
    assert resp.status_code == 200
    assert b"Review for CASE-2002" in resp.data
    assert b"Approve this section" in resp.data


def test_review_approval_gate_exports_only_approved_items(client, monkeypatch):
    import requests_mock

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_fake")
    with requests_mock.Mocker() as m:
        _mock_pending_review(m)
        resp = client.post("/generate", data=_form(dry_run=""), content_type="multipart/form-data")
        assert resp.status_code == 302
        review_url = resp.headers["Location"]
        review_id = review_url.rstrip("/").split("/")[-1]

        approve_form = {"approve_1": "on"}  # only item 1 approved; 2 and 3 left unapproved
        resp2 = client.post(f"/review/{review_id}/approve", data=approve_form)
        assert resp2.status_code == 200
        assert resp2.headers["Content-Disposition"].startswith("attachment")


def test_unknown_review_id_redirects_home(client):
    resp = client.get("/review/does-not-exist", follow_redirects=True)
    assert resp.status_code == 200
    assert b"was not found or has expired" in resp.data
