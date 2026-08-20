"""Export-download endpoint tests: gating, ownership, exact artifact."""

import asyncio

from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import FakeSuperDocsClient
from tests.test_orchestrator import _run_through_awaiting_approval, _workflow


def test_export_bytes_unavailable_before_export():
    wf = _workflow()
    _run_through_awaiting_approval(wf)
    assert wf.export_bytes() is None  # awaiting_approval -> no artifact


def test_export_bytes_unavailable_while_blocked():
    from tests.fakes import FakeSuperDocsClient as SD
    from app.workflow.models import WorkflowData, WorkflowState as WS
    from app.workflow.orchestrator import ReviewWorkflow

    fake = SD(approve_succeeds=False)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    assert wf.data.state == WS.BLOCKED
    assert wf.export_bytes() is None


def test_export_bytes_returns_exact_exported_bytes():
    wf = _workflow()
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    asyncio.run(wf.export_reviewed())
    bytes_, filename = wf.export_bytes()
    assert bytes_ == b"PK-reviewed-docx"  # exactly what the fake SuperDocs exported
    assert filename.endswith(".docx")


# ---- route-level tests (monkeypatched auth + workflow lookup) -------------


def _stub_workflow(owner: str, artifact) -> object:
    class Data:
        owner_session_id = owner

    class Stub:
        data = Data()

        def export_bytes(self):
            return artifact

    return Stub()


def _patch(monkeypatch, stub):
    from app.api import routes_workflow as rw

    async def fake_auth(request):
        return "tok"

    monkeypatch.setattr(rw, "require_auth", fake_auth)
    monkeypatch.setattr(rw, "_workflow_or_404", lambda request, wid: stub)


def test_download_forbidden_for_another_sessions_workflow(monkeypatch):
    _patch(monkeypatch, _stub_workflow("someone-else", (b"PK", "x.docx")))
    with TestClient(app) as client:
        r = client.get("/api/workflow/w1/export/download")
    assert r.status_code == 403
    assert "another session" in r.json()["detail"]


def test_download_unavailable_before_export(monkeypatch):
    _patch(monkeypatch, _stub_workflow("", None))
    with TestClient(app) as client:
        r = client.get("/api/workflow/w1/export/download")
    assert r.status_code == 409
    assert "export must complete first" in r.json()["detail"]


def test_download_returns_exact_artifact(monkeypatch):
    _patch(monkeypatch, _stub_workflow("", (b"PK-real-docx", "essay_reviewed.docx")))
    with TestClient(app) as client:
        r = client.get("/api/workflow/w1/export/download")
    assert r.status_code == 200
    assert r.content == b"PK-real-docx"
    assert "attachment" in r.headers["content-disposition"]
    assert "essay_reviewed.docx" in r.headers["content-disposition"]
    assert (
        r.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
