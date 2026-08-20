"""
test_templates.py -- coverage for the templates surface (GET /templates,
POST /workspaces/{id}/documents/draft) added to actually exercise the
templates surface this build's assigned card names, alongside the existing
upload path. Same "pure function / mocked client" style as test_main.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import db
import main
import models
from tests.fakes import FakeSuperDocsClient


@pytest.fixture()
def engine():
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


def test_ensure_templates_uploaded_uploads_the_library_once(fake_client):
    assert fake_client.templates == []
    main._ensure_templates_uploaded(fake_client)
    assert len(fake_client.templates) == len(main.TEMPLATE_LIBRARY)
    uploaded_filenames = {t["filename"] for t in fake_client.templates}
    assert uploaded_filenames == {entry["filename"] for entry in main.TEMPLATE_LIBRARY}


def test_ensure_templates_uploaded_is_idempotent(fake_client):
    """Regression guard for the assignment's 'idempotency wherever an
    operation costs money' bar -- calling this twice must not double-upload."""
    main._ensure_templates_uploaded(fake_client)
    first_count = len(fake_client.templates)
    main._ensure_templates_uploaded(fake_client)
    assert len(fake_client.templates) == first_count


def test_list_templates_endpoint_ensures_and_returns_templates(fake_client):
    resp = main.list_templates()
    assert len(resp["templates"]) == len(main.TEMPLATE_LIBRARY)


def test_draft_document_creates_a_real_document_with_sections(fake_client):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="ABC Medical Center", pack_name="Compliance Pack"))
    workspace_id = ws["id"]

    fake_client.queue_chat_html(
        '<div data-chunk-id="d1"><h1>Data Breach Notification Policy</h1></div>'
        '<div data-chunk-id="d2"><h2>Purpose</h2><p>Describe why this policy exists.</p></div>'
        '<div data-chunk-id="d3"><h2>Policy Statement</h2><p>Notify affected individuals within 24 hours.</p></div>'
    )

    resp = main.draft_document(
        workspace_id,
        main.DocumentDraftRequest(
            doc_type="policy",
            title="Data Breach Notification Policy",
            prompt="Draft a data breach notification policy for a mid-size clinic",
        ),
    )

    assert resp["document"]["doc_type"] == models.DocType.POLICY
    assert resp["document"]["title"] == "Data Breach Notification Policy"
    section_titles = {s["title"] for s in resp["sections"]}
    assert {"Purpose", "Policy Statement"} <= section_titles
    assert resp["version"]["source_format"] == models.SourceFormat.HTML
    assert resp["version"]["change_summary"].startswith("AI draft from template")

    # templates were ensured as a side effect of drafting, not just of GET /templates
    assert len(fake_client.templates) == len(main.TEMPLATE_LIBRARY)

    # v1 invariant preserved: raw_file_bytes really is populated, same as an
    # uploaded document -- verify by re-fetching the document
    detail = main.get_document(resp["document"]["id"], include_html=True)
    assert "Policy Statement" in detail["html"]


def test_draft_procedure_requires_parent_policy(fake_client):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="ABC Medical Center", pack_name="Compliance Pack"))
    workspace_id = ws["id"]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        main.draft_document(
            workspace_id,
            main.DocumentDraftRequest(doc_type="procedure", title="Some Procedure", prompt="Draft something"),
        )
    assert exc_info.value.status_code == 400


def test_draft_document_rejects_empty_prompt(fake_client):
    ws = main.create_workspace(main.WorkspaceCreate(organization_name="ABC Medical Center", pack_name="Compliance Pack"))
    workspace_id = ws["id"]

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        main.draft_document(workspace_id, main.DocumentDraftRequest(doc_type="policy", title="X", prompt="   "))
    assert exc_info.value.status_code == 400
