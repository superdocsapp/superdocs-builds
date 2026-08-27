from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_api_fixture_workflow_and_mcp():
    with TestClient(app) as client:
        created = client.post("/runs", json={"workspace_id": "api-workspace", "title": "API review"})
        assert created.status_code == 201
        run_id = created.json()["id"]
        upload = client.post(f"/runs/{run_id}/sources", files={"file": ("requirements.md", b"REQ-1 Ship safely\nREQ-2 Accessibility review\n", "text/markdown")})
        assert upload.status_code == 201
        client.post(f"/runs/{run_id}/sources", files={"file": ("tests.md", b"REQ-1 status: pass\n", "text/markdown")})
        client.post(f"/runs/{run_id}/sources", files={"file": ("failed-tests.md", b"REQ-1 status: fail\n", "text/markdown")})
        executed = client.post(f"/runs/{run_id}/execute")
        assert executed.status_code == 200
        snapshot = executed.json()
        assert snapshot["status"] == "awaiting_decisions"
        findings = [item for item in snapshot["findings"] if item["decision_required"]]
        assert findings
        partial = client.post(f"/runs/{run_id}/decisions", json={"decisions": [{"finding_id": findings[0]["id"], "state": "approved"}]})
        assert partial.status_code == 200
        assert partial.json()["missing_decisions"]
        all_decisions = [{"finding_id": item, "state": "approved"} for item in partial.json()["missing_decisions"]]
        done = client.post(f"/runs/{run_id}/decisions", json={"decisions": all_decisions})
        assert done.status_code == 200
        assert done.json()["status"] == "completed"
        mcp = client.post("/mcp", json={"operation": "get_report", "run_id": run_id})
        assert mcp.status_code == 200
        assert mcp.json()["result"]["report"]["schema_version"] == "1.0"


def test_api_rejects_unknown_and_duplicate_decisions():
    with TestClient(app) as client:
        run_id = client.post("/runs", json={"workspace_id": "api-workspace", "title": "Decision test"}).json()["id"]
        client.post(f"/runs/{run_id}/sources", files={"file": ("requirements.md", b"REQ-1 Ship\n", "text/markdown")})
        snapshot = client.post(f"/runs/{run_id}/execute").json()
        finding_id = next(item["id"] for item in snapshot["findings"] if item["decision_required"])
        duplicate = client.post(f"/runs/{run_id}/decisions", json={"decisions": [{"finding_id": finding_id, "state": "approved"}, {"finding_id": finding_id, "state": "rejected"}]})
        assert duplicate.status_code == 422
        unknown = client.post(f"/runs/{run_id}/decisions", json={"decisions": [{"finding_id": "fnd_unknown", "state": "approved"}]})
        assert unknown.status_code == 422


def test_upload_rejects_unsupported_format():
    with TestClient(app) as client:
        run_id = client.post("/runs", json={"workspace_id": "api-workspace", "title": "Format test"}).json()["id"]
        response = client.post(f"/runs/{run_id}/sources", files={"file": ("secret.exe", b"not supported", "application/octet-stream")})
        assert response.status_code == 422
