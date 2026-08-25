from backend.app.services.demo import DEMO_CLOSE_ID
from backend.app.services.pdf import build_pdf
from backend.app.services.templates import DEFAULT_TEMPLATE_ID, get_template, suggest_document_type


def test_demo_close_audit_trail_agrees_with_its_state(client, auth):
    """The seeded fixture used to claim events that contradicted the data it shipped."""
    close = client.get(f"/api/v1/closes/{DEMO_CLOSE_ID}", headers=auth).json()
    trail = client.get(f"/api/v1/closes/{DEMO_CLOSE_ID}/audit", headers=auth).json()

    signed = [item for item in close["signoffs"] if item["status"] == "APPROVED"]
    signoff_events = [entry for entry in trail if entry["event"] == "SIGNOFF_APPROVED"]
    assert len(signed) == len(signoff_events)
    assert {item["person"] for item in signed} == {entry["actor"] for entry in signoff_events}

    uploads = [entry for entry in trail if entry["event"] == "DOCUMENT_UPLOADED"]
    assert len(uploads) == len(close["documents"])

    completed = [item for item in close["checklist"] if item["status"] == "COMPLETE"]
    assert len(completed) == len([entry for entry in trail if entry["event"] == "CHECKLIST_COMPLETED"])

    # It opens with real outstanding work rather than a finished-looking fiction.
    assert close["reviews"] == []
    assert any(item["status"] != "READY" for item in close["documents"])


def test_demo_documents_are_real_openable_files(client, auth):
    close = client.get(f"/api/v1/closes/{DEMO_CLOSE_ID}", headers=auth).json()

    for document in close["documents"]:
        response = client.get(
            f"/api/v1/closes/{DEMO_CLOSE_ID}/documents/{document['id']}/content", headers=auth
        )
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-")
        assert len(response.content) == document["size"]


def test_demo_close_is_created_once(client, auth):
    from backend.app.services.demo import ensure_demo_close

    before = client.get(f"/api/v1/closes/{DEMO_CLOSE_ID}", headers=auth).json()
    ensure_demo_close()
    after = client.get(f"/api/v1/closes/{DEMO_CLOSE_ID}", headers=auth).json()

    assert before["created_at"] == after["created_at"]
    assert len(after["documents"]) == len(before["documents"])


def test_filename_classification_matches_required_types():
    required = get_template(DEFAULT_TEMPLATE_ID)["required_document_types"]

    assert suggest_document_type("Trial Balance.pdf", required) == "Trial Balance"
    assert suggest_document_type("Bank Recon.pdf", required) == "Bank Reconciliation"
    assert suggest_document_type("Accrual Support.pdf", required) == "Accruals"
    assert suggest_document_type("Payroll Register.pdf", required) == "Payroll"
    assert suggest_document_type("Fixed Assets.pdf", required) == "Fixed Assets"
    assert suggest_document_type("scan_0001.pdf", required) is None


def test_generated_pdf_is_structurally_valid():
    data = build_pdf("Title", ["line one", "line (with) parens", "unicode — dash"])

    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in data
    assert data.count(b" obj\n") == 6
