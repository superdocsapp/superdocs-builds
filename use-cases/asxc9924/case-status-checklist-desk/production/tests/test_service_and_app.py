import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from case_status_desk import db as db_module
from case_status_desk import service
from case_status_desk.db import Base, CaseRecord, DocumentRequirement, GeneratedLetter
from case_status_desk.superdocs_client import SuperDocsClient


@pytest.fixture()
def session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()

    s.add(CaseRecord(
        case_id="CASE-9001", client_name="Test Client", client_language="en",
        case_type="employment-based petition", stage="documents_pending",
        documents=[
            DocumentRequirement(name="Passport", form_type="certified copy", received=False,
                                 due_date=date(2026, 9, 1)),
            DocumentRequirement(name="Photo ID", form_type="scan", received=True),
        ],
    ))
    s.commit()
    yield s
    s.close()


class FakeSuperDocsClient:
    """Stand-in for SuperDocsClient so tests don't hit the network. Its
    chat() fabricates a realistic, checklist-accurate letter body so
    tests that exercise draft->approve->export (not validation itself)
    get a letter that passes automated validation on the happy path."""
    def __init__(self):
        self.renamed = {}
        self.archived = []

    def chat(self, session_id, message, document_html=None):
        from case_status_desk.cases import STAGE_LANGUAGE
        # Build a validation-passing letter body from whatever stage/
        # checklist text was embedded in the instruction, so callers
        # don't need to hand-roll a matching letter per test.
        import re
        stage_match = re.search(r'status summary.*?: "(.*?)"', message)
        next_match = re.search(r'next-step language: "(.*?)"', message)
        summary = stage_match.group(1) if stage_match else ""
        next_step = next_match.group(1) if next_match else ""
        checklist_match = re.search(r"Outstanding documents:\n(.*?)\n\nWrite", message, re.S)
        checklist = checklist_match.group(1) if checklist_match else ""
        html = f"<p>{summary}</p><p>{next_step}</p><p>{checklist}</p>"

        class R:
            reply_text = "drafted"
            updated_html = html
        return R()

    def export(self, session_id, fmt="docx", filename=None):
        return b"FAKE-DOCX-BYTES"

    def list_documents(self, limit=50):
        return [{"id": "doc_fake123", "title": "Untitled"}]

    def rename_document(self, document_id, title):
        self.renamed[document_id] = title
        return {"id": document_id, "title": title}

    def archive_document(self, document_id, force=False):
        self.archived.append((document_id, force))
        return {"id": document_id, "archived": True}


def test_outstanding_documents_reflects_live_state(session):
    from case_status_desk.cases import case_from_db_record
    record = session.get(CaseRecord, "CASE-9001")
    case = case_from_db_record(record)
    outstanding = case.outstanding_documents()
    assert len(outstanding) == 1
    assert outstanding[0].name == "Passport"
    assert not case.is_fully_documented()


def test_draft_requires_real_case(session):
    with pytest.raises(service.NotFoundError):
        service.draft_letter(session, FakeSuperDocsClient(), "NOPE", requested_by="tester")


def test_export_blocked_until_approved(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    assert letter.status == "awaiting_approval"

    with pytest.raises(service.ApprovalRequiredError):
        service.export_letter(session, FakeSuperDocsClient(), letter.id)

    approved = service.approve_letter(session, letter.id, approved_by="supervisor")
    assert approved.status == "approved"
    assert approved.approved_by == "supervisor"

    path = service.export_letter(session, FakeSuperDocsClient(), letter.id)
    assert path.exists()
    assert path.read_bytes() == b"FAKE-DOCX-BYTES"

    refreshed = session.get(GeneratedLetter, letter.id)
    assert refreshed.status == "exported"


def test_letter_snapshot_is_captured_at_draft_time(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    snapshot = json.loads(letter.outstanding_snapshot)
    assert snapshot == [{"name": "Passport", "form_type": "certified copy", "due_date": "2026-09-01"}]


def test_seed_from_json_maps_required_documents_key(tmp_path, monkeypatch):
    """Regression test: the seeder must read 'required_documents' (the
    actual schema key), not a different key -- otherwise every checklist
    silently seeds empty."""
    engine = create_engine(f"sqlite:///{tmp_path}/seed.db", future=True)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine, future=True))
    db_module.init_db()

    sample = tmp_path / "cases.json"
    sample.write_text(json.dumps([{
        "case_id": "CASE-1", "client_name": "A", "case_type": "x", "stage": "filed", "language": "en",
        "required_documents": [{"name": "Doc A", "form_type": "copy", "received": False}],
    }]))
    db_module.seed_from_json(str(sample))

    with db_module.get_session() as s:
        record = s.get(CaseRecord, "CASE-1")
        assert len(record.documents) == 1
        assert record.documents[0].name == "Doc A"


def test_auth_dependency_rejects_missing_and_bad_keys(monkeypatch):
    from fastapi import HTTPException
    from case_status_desk.auth import require_staff_user

    monkeypatch.setenv("STAFF_API_KEYS", "sk_good:Alice:admin")

    with pytest.raises(HTTPException) as exc:
        require_staff_user(authorization="")
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        require_staff_user(authorization="Bearer sk_bad")
    assert exc.value.status_code == 401

    user = require_staff_user(authorization="Bearer sk_good")
    assert user.name == "Alice"
    assert user.role == "admin"


def test_preparer_cannot_approve(monkeypatch):
    from fastapi import HTTPException
    from case_status_desk.auth import require_approver

    monkeypatch.setenv("STAFF_API_KEYS", "sk_prep:Priya:preparer,sk_appr:Marco:approver")

    with pytest.raises(HTTPException) as exc:
        require_approver(authorization="Bearer sk_prep")
    assert exc.value.status_code == 403

    user = require_approver(authorization="Bearer sk_appr")
    assert user.name == "Marco"


def test_two_part_key_defaults_to_admin(monkeypatch):
    from case_status_desk.auth import require_staff_user, require_approver

    monkeypatch.setenv("STAFF_API_KEYS", "sk_legacy:Legacy User")
    user = require_staff_user(authorization="Bearer sk_legacy")
    assert user.role == "admin"
    assert require_approver(authorization="Bearer sk_legacy").name == "Legacy User"


def test_self_approval_blocked(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="Priya")
    with pytest.raises(service.SelfApprovalError):
        service.approve_letter(session, letter.id, approved_by="Priya")

    # a different approver succeeds
    approved = service.approve_letter(session, letter.id, approved_by="Marco")
    assert approved.approved_by == "Marco"


def test_import_adapter_json_source(tmp_path):
    from case_status_desk.case_import import JsonFileCaseSource, sync_cases
    from case_status_desk import db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path}/import.db", future=True)
    Session = sessionmaker(bind=engine, future=True)
    from case_status_desk.db import Base
    Base.metadata.create_all(engine)

    sample = tmp_path / "cases.json"
    sample.write_text(json.dumps([{
        "case_id": "CASE-77", "client_name": "Imported Client", "case_type": "family petition",
        "stage": "filed", "language": "es",
        "required_documents": [
            {"name": "Birth Certificate", "form_type": "certified copy", "received": False,
             "due_date": "2026-10-01"},
        ],
    }]))

    count = sync_cases(JsonFileCaseSource(sample), Session)
    assert count == 1

    from case_status_desk.db import CaseRecord
    with Session() as s:
        record = s.get(CaseRecord, "CASE-77")
        assert record.client_name == "Imported Client"
        assert record.client_language == "es"
        assert len(record.documents) == 1
        assert record.documents[0].name == "Birth Certificate"


def test_import_adapter_is_idempotent_upsert(tmp_path):
    """Re-running the import for the same case should update it in
    place, not duplicate it -- this is what keeps the checklist from
    ever going stale."""
    from case_status_desk.case_import import JsonFileCaseSource, sync_cases
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from case_status_desk.db import Base, CaseRecord

    engine = create_engine(f"sqlite:///{tmp_path}/import2.db", future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    sample = tmp_path / "cases.json"
    sample.write_text(json.dumps([{
        "case_id": "CASE-77", "client_name": "A", "case_type": "x", "stage": "filed", "language": "en",
        "required_documents": [{"name": "Doc", "form_type": "copy", "received": False}],
    }]))
    sync_cases(JsonFileCaseSource(sample), Session)

    # Now the CMS says the document was received and stage moved on
    sample.write_text(json.dumps([{
        "case_id": "CASE-77", "client_name": "A", "case_type": "x", "stage": "rfe_received", "language": "en",
        "required_documents": [{"name": "Doc", "form_type": "copy", "received": True}],
    }]))
    sync_cases(JsonFileCaseSource(sample), Session)

    with Session() as s:
        records = s.query(CaseRecord).filter_by(case_id="CASE-77").all()
        assert len(records) == 1
        assert records[0].stage == "rfe_received"
        assert records[0].documents[0].received is True


def test_export_links_superdocs_document(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    service.approve_letter(session, letter.id, approved_by="supervisor")

    client = FakeSuperDocsClient()
    service.export_letter(session, client, letter.id)

    refreshed = session.get(GeneratedLetter, letter.id)
    assert refreshed.superdocs_document_id == "doc_fake123"
    assert "CASE-9001" in refreshed.superdocs_document_title
    assert client.renamed["doc_fake123"] == refreshed.superdocs_document_title


def test_export_survives_superdocs_document_lookup_failure(session, tmp_path, monkeypatch):
    """If linking the SuperDocs File fails for any reason, the export
    itself must still succeed -- Files linking is best-effort, not a
    hard dependency of getting the .docx out."""
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    service.approve_letter(session, letter.id, approved_by="supervisor")

    class BrokenLinkClient(FakeSuperDocsClient):
        def list_documents(self, limit=50):
            raise RuntimeError("network blip")

    path = service.export_letter(session, BrokenLinkClient(), letter.id)
    assert path.exists()
    refreshed = session.get(GeneratedLetter, letter.id)
    assert refreshed.status == "exported"
    assert refreshed.superdocs_document_id is None


def test_archive_letter_document(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    service.approve_letter(session, letter.id, approved_by="supervisor")
    client = FakeSuperDocsClient()
    service.export_letter(session, client, letter.id)

    service.archive_letter_document(session, client, letter.id)
    assert client.archived == [("doc_fake123", False)]


def test_archive_letter_document_noop_when_unlinked(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    client = FakeSuperDocsClient()
    # never exported/linked
    service.archive_letter_document(session, client, letter.id)
    assert client.archived == []


def test_draft_letter_blocks_on_validation_error_when_requested(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class BadDraftClient(FakeSuperDocsClient):
        def chat(self, session_id, message, document_html=None):
            class R:
                reply_text = "drafted"
                updated_html = "<p>Sorry, nothing to report.</p>"  # drops everything
            return R()

    with pytest.raises(service.ValidationFailedError):
        service.draft_letter(session, BadDraftClient(), "CASE-9001", requested_by="tester",
                              block_on_validation_error=True)


def test_draft_letter_does_not_block_by_default_but_records_failure(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class BadDraftClient(FakeSuperDocsClient):
        def chat(self, session_id, message, document_html=None):
            class R:
                reply_text = "drafted"
                updated_html = "<p>Sorry, nothing to report.</p>"
            return R()

    letter = service.draft_letter(session, BadDraftClient(), "CASE-9001", requested_by="tester")
    assert letter.status == "awaiting_approval"
    assert letter.validation_passed is False
    import json as _json
    issues = _json.loads(letter.validation_issues)
    assert any(i["severity"] == "error" for i in issues)


def test_approve_blocked_on_failed_validation_without_override(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class BadDraftClient(FakeSuperDocsClient):
        def chat(self, session_id, message, document_html=None):
            class R:
                reply_text = "drafted"
                updated_html = "<p>Sorry, nothing to report.</p>"
            return R()

    letter = service.draft_letter(session, BadDraftClient(), "CASE-9001", requested_by="tester")
    with pytest.raises(service.ValidationFailedError):
        service.approve_letter(session, letter.id, approved_by="supervisor")


def test_approve_succeeds_with_explicit_override(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class BadDraftClient(FakeSuperDocsClient):
        def chat(self, session_id, message, document_html=None):
            class R:
                reply_text = "drafted"
                updated_html = "<p>Sorry, nothing to report.</p>"
            return R()

    letter = service.draft_letter(session, BadDraftClient(), "CASE-9001", requested_by="tester")
    approved = service.approve_letter(session, letter.id, approved_by="supervisor", override_validation=True)
    assert approved.status == "approved"
    assert approved.validation_overridden_by == "supervisor"


def test_good_draft_passes_validation_and_approves_normally(session, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    letter = service.draft_letter(session, FakeSuperDocsClient(), "CASE-9001", requested_by="tester")
    assert letter.validation_passed is True
    approved = service.approve_letter(session, letter.id, approved_by="supervisor")
    assert approved.status == "approved"
    assert approved.validation_overridden_by is None
