from __future__ import annotations

from fastapi.testclient import TestClient

from config.credit import CREDIT_ROLE_IDS
from llm.glm import GLMError
from main import app
from schemas.declare import AnalysisProviderResponse
from utils.review import review_issues
from utils.statements import render_statements

client = TestClient(app)

AUTHORS = [{"id": "shashank", "name": "Shashank"}, {"id": "rahul", "name": "Rahul"}]


def facts(**overrides):
    value = {
        "authors": AUTHORS,
        "contributions": [{"authorId": "shashank", "evidence": "designed the study", "roleIds": ["conceptualization"], "status": "approved"}],
        "funding": {"status": "none", "evidence": "No funding."},
        "conflicts": {"status": "none", "items": []},
    }
    value.update(overrides)
    return value


def test_health_and_credit_ids():
    response = client.get("/health")
    assert response.json() == {"success": True, "service": "declare"}
    assert CREDIT_ROLE_IDS == {
        "conceptualization", "data_curation", "formal_analysis", "funding_acquisition", "investigation", "methodology",
        "project_administration", "resources", "software", "supervision", "validation", "visualization",
        "writing_original_draft", "writing_review_editing",
    }


def test_analyze_valid_mapping_and_empty_conflicts(monkeypatch):
    async def fake_glm(prompt):
        return {
            "contributions": [{"authorId": "shashank", "evidence": "designed the study", "roleIds": ["conceptualization"], "status": "proposed"}],
            "funding": {"status": "none", "evidence": "No funding."},
            "conflicts": {"status": "none", "items": []},
        }
    monkeypatch.setattr("routes.analyze.analyze_with_glm", fake_glm)
    response = client.post("/api/declare/analyze", json={"authors": AUTHORS, "contributions": "Shashank designed the study", "funding": "No funding.", "conflicts": ""})
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["contributions"][0]["roleIds"] == ["conceptualization"]
    assert body["data"]["conflicts"] == {"status": "unknown", "items": []}


def test_analyze_ambiguous_unknown_author_missing_evidence_and_invalid_role(monkeypatch):
    async def fake_glm(prompt):
        return {
            "contributions": [
                {"authorId": "shashank", "evidence": "helped with the research", "roleIds": [], "status": "ambiguous"},
                {"authorId": "not-listed", "evidence": "designed the study", "roleIds": ["conceptualization"], "status": "proposed"},
                {"authorId": "rahul", "evidence": "", "roleIds": ["bogus"], "status": "proposed"},
            ],
            "funding": {"status": "unknown", "evidence": ""}, "conflicts": {"status": "unknown", "items": []},
        }
    monkeypatch.setattr("routes.analyze.analyze_with_glm", fake_glm)
    response = client.post("/api/declare/analyze", json={"authors": AUTHORS, "contributions": "Shashank helped with the research.", "funding": "", "conflicts": ""})
    data = response.json()["data"]
    assert data["contributions"] == [
        {"authorId": "shashank", "evidence": "helped with the research", "roleIds": [], "status": "ambiguous"},
        {"authorId": "rahul", "evidence": "", "roleIds": [], "status": "ambiguous"},
    ]
    assert {item["type"] for item in data["issues"]} >= {"UNKNOWN_AUTHOR", "MISSING_EVIDENCE"}


def test_funding_acquisition_requires_explicit_acquisition(monkeypatch):
    async def fake_glm(prompt):
        return {
            "contributions": [{"authorId": "shashank", "evidence": "received funding", "roleIds": ["funding_acquisition"], "status": "proposed"}],
            "funding": {"status": "reported", "funder": "Foundation", "evidence": "Foundation funded the study"},
            "conflicts": {"status": "none", "items": []},
        }
    monkeypatch.setattr("routes.analyze.analyze_with_glm", fake_glm)
    response = client.post("/api/declare/analyze", json={"authors": AUTHORS, "contributions": "Shashank received funding", "funding": "Foundation funded the study", "conflicts": "None."})
    data = response.json()["data"]
    assert data["contributions"][0]["roleIds"] == []
    assert data["contributions"][0]["status"] == "ambiguous"
    assert any(issue["type"] == "INVALID_CREDIT_ROLE" for issue in data["issues"])


def test_glm_malformed_and_failed_responses(monkeypatch):
    async def malformed(prompt):
        return {"contributions": [{"authorId": "shashank", "evidence": "x", "roleIds": [], "status": "wrong"}]}
    monkeypatch.setattr("routes.analyze.analyze_with_glm", malformed)
    response = client.post("/api/declare/analyze", json={"authors": AUTHORS, "contributions": "x", "funding": "", "conflicts": ""})
    assert response.status_code == 400 and response.json()["error"] == "INVALID_ANALYZE_REQUEST_OR_GLM_RESPONSE"

    async def failed(prompt):
        raise GLMError("failed")
    monkeypatch.setattr("routes.analyze.analyze_with_glm", failed)
    response = client.post("/api/declare/analyze", json={"authors": AUTHORS, "contributions": "x", "funding": "", "conflicts": ""})
    assert response.status_code == 502 and response.json()["error"] == "DECLARE_ANALYSIS_FAILED"


def test_statement_review_errors_and_deterministic_rendering():
    invalid = facts(contributions=[{"authorId": "missing", "evidence": "x", "roleIds": ["invalid"], "status": "ambiguous"}], funding={"status": "reported", "evidence": ""}, conflicts={"status": "unknown", "items": []})
    response = client.post("/api/declare/statements", json=invalid)
    assert response.status_code == 422
    assert response.json()["error"] == "REVIEW_REQUIRED"

    valid = facts(contributions=[
        {"authorId": "rahul", "evidence": "built software", "roleIds": ["software", "conceptualization", "software"], "status": "approved"},
        {"authorId": "shashank", "evidence": "designed", "roleIds": ["methodology"], "status": "approved"},
    ], funding={"status": "reported", "funder": "ACME & Co", "awardNumber": "G<1>", "evidence": "ACME"}, conflicts={"status": "reported", "items": [{"disclosure": "has shares", "evidence": "has shares"}]})
    response = client.post("/api/declare/statements", json=valid)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "contributionStatement": "Author Contributions\n\nShashank: Methodology.\nRahul: Conceptualization, Software.",
        "fundingStatement": "Funding\n\nThis work was supported by ACME & Co (grant G<1>).",
        "conflictStatement": "Competing Interests\n\nhas shares",
    }


class FakeResponse:
    def __init__(self, data=None, content=b"", content_type="application/json"):
        self._data = data
        self.content = content
        self.headers = {"content-type": content_type}
    def json(self):
        return self._data


def test_superdocs_success_paths_and_instruction(monkeypatch):
    calls = []
    async def fake_provider(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/v1/documents/export":
            return FakeResponse(content=b"DOCX", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return FakeResponse({"job_id": "job-1", "status": "queued"})
    monkeypatch.setattr("routes.superdocs.provider_request", fake_provider)
    assert client.post("/api/superdocs/upload", json={"sessionId": "safe-session-1", "filename": "a.docx", "fileBase64": "YWJj", "returnHtml": True}).status_code == 200
    assert client.post("/api/superdocs/apply", json={"sessionId": "safe-session-1", "facts": facts(), "approvalMode": "approve_all"}).status_code == 200
    assert client.get("/api/superdocs/jobs/job-1").status_code == 200
    assert client.post("/api/superdocs/approve", json={"sessionId": "safe-session-1", "jobId": "job-1", "approved": True, "changes": [{"changeId": "c1", "approved": True}]}).status_code == 200
    exported = client.post("/api/superdocs/export", json={"sessionId": "safe-session-1", "format": "docx"})
    assert exported.status_code == 200 and exported.content == b"DOCX"
    apply_payload = calls[1][2]
    assert apply_payload["approval_mode"] == "approve_all"
    assert "Append the exact HTML block below at the very end" in apply_payload["message"]
    assert '<section data-declare-statements="true">' in apply_payload["message"]
    assert calls[3][2]["changes"] == [{"change_id": "c1", "approved": True}]


def test_superdocs_failures_and_envelopes(monkeypatch):
    async def failed(*args, **kwargs):
        raise SuperDocsError("SUPERDOCS_PROVIDER_FAILED")
    from utils.superdocs import SuperDocsError
    monkeypatch.setattr("routes.superdocs.provider_request", failed)
    cases = [
        ("/api/superdocs/upload", {"sessionId": "s", "filename": "a", "fileBase64": "x", "returnHtml": True}, "SUPERDOCS_UPLOAD_FAILED"),
        ("/api/superdocs/apply", {"sessionId": "s", "facts": facts(), "approvalMode": "approve_all"}, "SUPERDOCS_APPLY_FAILED"),
        ("/api/superdocs/approve", {"sessionId": "s", "jobId": "j", "approved": True}, "SUPERDOCS_APPROVE_FAILED"),
        ("/api/superdocs/export", {"sessionId": "s", "format": "docx"}, "SUPERDOCS_EXPORT_FAILED"),
    ]
    for path, payload, code in cases:
        response = client.post(path, json=payload)
        assert response.status_code == 502 and response.json()["error"] == code
    assert client.post("/api/superdocs/approve", json={"sessionId": "s", "approved": True}).json()["error"] == "MISSING_JOB_ID"


def test_invalid_requests_and_payload_limit():
    response = client.post("/api/declare/statements", json={})
    assert response.status_code == 400
    assert response.json()["error"] == "INVALID_STATEMENTS_REQUEST"
    response = client.post("/api/superdocs/upload", json={"sessionId": "bad space", "filename": "a", "fileBase64": "x", "returnHtml": True})
    assert response.status_code == 400 and response.json()["error"] == "INVALID_SUPERDOCS_REQUEST"
    response = client.post("/api/superdocs/upload", content=b"x" * (32 * 1024 * 1024 + 1), headers={"content-type": "application/json", "content-length": str(32 * 1024 * 1024 + 1)})
    assert response.status_code == 413
    assert response.json()["message"] == "The uploaded manuscript is too large. Please use a file smaller than 20 MB."
