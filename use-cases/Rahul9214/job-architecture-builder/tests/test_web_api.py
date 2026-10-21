"""Reviewer API. Offline; no live SuperDocs calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_architecture.web.app import create_app
from job_architecture.web.service import WorkspaceService
from job_architecture.web.store import WorkspaceStore

SECRET_MARKERS = ("SUPERDOCS_API_KEY", "sk_live", "Authorization", "Bearer ")


@pytest.fixture()
def client() -> TestClient:
    app = create_app(WorkspaceService(WorkspaceStore()))
    return TestClient(app)


def _analyze(client: TestClient, corpus_id: str = "corpus-a"):
    response = client.post(f"/api/corpora/{corpus_id}/analyze")
    assert response.status_code == 200, response.text
    return response.json()


def test_spa_fallback_serves_index_when_built(client: TestClient) -> None:
    dist = Path(__file__).resolve().parents[1] / "web" / "dist" / "index.html"
    if not dist.is_file():
        pytest.skip("frontend production build is not present")
    for path in (
        "/",
        "/architecture",
        "/exceptions",
        "/framework",
        "/profiles",
        "/impact",
        "/review",
        "/export",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Job Architecture and Levelling Framework Builder" in response.text


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_corpora(client: TestClient) -> None:
    response = client.get("/api/corpora")
    assert response.status_code == 200
    ids = {item["corpus_id"] for item in response.json()["corpora"]}
    assert ids == {"corpus-a", "corpus-b"}
    northstar = next(item for item in response.json()["corpora"] if item["corpus_id"] == "corpus-a")
    meridian = next(item for item in response.json()["corpora"] if item["corpus_id"] == "corpus-b")
    assert northstar["organization"] == "Northstar Systems"
    assert meridian["organization"] == "Meridian HealthTech"
    assert northstar["role_count"] == 21
    assert meridian["role_count"] == 12
    assert northstar["roles"][0]["filename"]
    assert northstar["analyzed"] is False


def test_invalid_corpus(client: TestClient) -> None:
    response = client.get("/api/corpora/corpus-missing")
    assert response.status_code == 404
    assert response.json()["code"] == "corpus_not_found"


def test_architecture_requires_analyze(client: TestClient) -> None:
    response = client.get("/api/architecture/corpus-a")
    assert response.status_code == 409
    assert response.json()["code"] == "not_analyzed"


def test_architecture_summary(client: TestClient) -> None:
    payload = _analyze(client, "corpus-a")
    metrics = payload["metrics"]
    assert metrics["total_roles"] == 21
    assert metrics["proposed_families"] >= 1
    assert metrics["tracks"] >= 2
    assert metrics["strong_fits"] >= 1
    assert metrics["provisional"] >= 1
    assert metrics["misfits"] >= 1
    assert "unclustered" in metrics
    assert "bridge_roles" in metrics
    assert payload["clusters"]
    fetched = client.get("/api/architecture/corpus-a")
    assert fetched.status_code == 200
    assert fetched.json()["organization"] == "Northstar Systems"


def test_role_detail_and_invalid_role(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    missing = client.get("/api/architecture/corpus-a/roles/not-a-role")
    assert missing.status_code == 404
    detail = client.get("/api/architecture/corpus-a/roles/ns-swe-ii-payments")
    assert detail.status_code == 200
    body = detail.json()
    assert body["title"]
    assert body["team"]
    assert body["fit_status"] == "strong_fit"
    assert body["level"] in {"IC4", "IC5"}
    assert body["signals"]["scope"]
    assert body["supporting_evidence"]
    assert body["source_references"]


def test_title_conflict_evidence_from_assessments(client: TestClient) -> None:
    payload = _analyze(client, "corpus-a")
    conflicts = {item["role_id"]: item for item in payload["title_conflicts"]}
    senior = client.get("/api/architecture/corpus-a/roles/ns-senior-swe-internal-tools").json()
    modest = client.get("/api/architecture/corpus-a/roles/ns-swe-ii-payments").json()
    manager = client.get("/api/architecture/corpus-a/roles/ns-em-developer-experience").json()
    genuine = client.get("/api/architecture/corpus-a/roles/ns-em-platform").json()
    aligned = client.get("/api/architecture/corpus-a/roles/ns-swe-backend").json()
    assert senior["title_conflict"]["kind"] == "title_seniority_overstates_evidence"
    assert modest["title_conflict"]["kind"] == "title_understates_scope"
    assert manager["title_conflict"]["kind"] == "title_management_conflict"
    assert genuine["title_conflict"] is None
    assert aligned["title_conflict"] is None
    assert conflicts["ns-senior-swe-internal-tools"]["title_conflict"]["title_signal"]
    assert conflicts["ns-swe-ii-payments"]["title_conflict"]["evidence_result"]
    assert "ns-em-platform" not in conflicts
    assert "ns-swe-backend" not in conflicts
    corpus_b = _analyze(client, "corpus-b")
    b_conflicts = {item["role_id"]: item for item in corpus_b["title_conflicts"]}
    principal = client.get("/api/architecture/corpus-b/roles/mh-principal-engineer-widgets").json()
    assert principal["title_conflict"]["kind"] == "title_seniority_overstates_evidence"
    assert "mh-principal-engineer-widgets" in b_conflicts


def test_exceptions(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    payload = client.get("/api/exceptions/corpus-a").json()
    assert payload["provisional"]
    assert payload["misfit"]
    misfit = payload["misfit"][0]
    assert misfit["status"] == "requires_architecture_decision"
    assert misfit["why"]
    assert misfit["has_normalized_profile"] is False


def test_framework_and_profiles(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    framework = client.get("/api/framework/corpus-a").json()
    labels = {item["label"] for item in framework["levels"]}
    assert {"IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3"} <= labels
    assert framework["purpose"]
    assert framework["competency_matrices"]
    assert "scope" in framework["editable_dimensions"]
    assert framework["default_occupied_level_id"]
    listing = client.get("/api/profiles/corpus-a").json()
    assert listing["profiles"]
    profile_id = next(item["profile_id"] for item in listing["profiles"] if item["level_label"] == "IC4")
    detail = client.get(f"/api/profiles/corpus-a/{profile_id}").json()
    assert detail["level_expectations"]
    assert detail["role_purpose"]
    assert "Scope:" in detail["level_expectations"]
    missing = client.get("/api/profiles/corpus-a/profile-does-not-exist")
    assert missing.status_code == 404


def test_malformed_level_edit(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    empty = client.post("/api/impact/corpus-a/level-change", json={"level_id": "ic4", "dimension": "scope", "value": ""})
    assert empty.status_code == 400
    unknown = client.post(
        "/api/impact/corpus-a/level-change",
        json={"level_id": "ic4", "dimension": "salary", "value": "nope"},
    )
    assert unknown.status_code == 400
    missing_level = client.post(
        "/api/impact/corpus-a/level-change",
        json={"level_id": "not-a-level", "dimension": "scope", "value": "x"},
    )
    assert missing_level.status_code == 404


def test_impact_and_update_planning(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    impact = client.post(
        "/api/impact/corpus-a/level-change",
        json={
            "level_id": "ic4",
            "dimension": "scope",
            "value": "Cross-team domain plus an explicit sequencing veto for reviewer demonstration.",
        },
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert "scope" in body["changed_dimensions"]
    assert body["affected_profiles_count"] >= 1
    assert body["unaffected_profiles_count"] >= 1
    planned = client.post(
        "/api/updates/corpus-a/plan",
        json={
            "level_id": "ic4",
            "dimension": "scope",
            "value": "Cross-team domain plus an explicit sequencing veto for reviewer demonstration.",
        },
    )
    assert planned.status_code == 200
    plans = planned.json()["plans"]
    assert plans
    assert plans[0]["before"] != plans[0]["after"]
    assert plans[0]["preserved_rendered_fields"]
    assert "complexity" in plans[0]["preserved_rendered_fields"]


def test_no_affected_profiles_for_unoccupied_level(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    impact = client.post(
        "/api/impact/corpus-a/level-change",
        json={
            "level_id": "m3",
            "dimension": "scope",
            "value": "Function-wide people strategy with an added reviewer note.",
        },
    )
    assert impact.status_code == 200
    assert impact.json()["affected_profiles_count"] == 0
    planned = client.post(
        "/api/updates/corpus-a/plan",
        json={
            "level_id": "m3",
            "dimension": "scope",
            "value": "Function-wide people strategy with an added reviewer note.",
        },
    )
    assert planned.json()["plans"] == []


def test_review_empty_then_approve_and_preserve(client: TestClient) -> None:
    empty = client.get("/api/review/corpus-a")
    assert empty.status_code == 200
    assert empty.json()["empty"] is True
    _analyze(client, "corpus-a")
    client.post(
        "/api/updates/corpus-a/plan",
        json={
            "level_id": "ic4",
            "dimension": "scope",
            "value": "Cross-team domain plus an explicit sequencing veto for reviewer demonstration.",
        },
    )
    review = client.get("/api/review/corpus-a").json()
    assert review["mutation_applied"] is False
    assert review["domain_applied"] is False
    assert review["review_outcome"] == "pending"
    items = [{"plan_id": plan["plan_id"], "approved": True} for plan in review["plans"]]
    decided = client.post("/api/review/corpus-a/decisions", json={"items": items})
    assert decided.status_code == 200
    applied = client.post("/api/review/corpus-a/apply")
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["review_outcome"] == "approved"
    assert payload["mutation_applied"] is True
    assert payload["domain_applied"] is True
    assert payload["preservation"]["ok"] is True
    assert payload["preservation"]["unrelated_sections_preserved"] is True
    assert payload["preservation"]["unchanged_section_count"] >= 1
    again = client.post("/api/review/corpus-a/apply")
    assert again.json()["idempotent"] is True


def test_rejected_plan_is_not_applied(client: TestClient) -> None:
    _analyze(client, "corpus-a")
    planned = client.post(
        "/api/updates/corpus-a/plan",
        json={"level_id": "ic4", "dimension": "scope", "value": "A rejected scope rewrite."},
    )
    items = [{"plan_id": plan["plan_id"], "approved": False} for plan in planned.json()["plans"]]
    client.post("/api/review/corpus-a/decisions", json={"items": items})
    applied = client.post("/api/review/corpus-a/apply").json()
    assert applied["review_outcome"] == "rejected"
    assert applied["mutation_applied"] is False
    assert applied["domain_applied"] is False


def test_no_secrets_in_api_responses(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_live_should_never_appear")
    _analyze(client, "corpus-a")
    paths = [
        "/api/health",
        "/api/corpora",
        "/api/architecture/corpus-a",
        "/api/exceptions/corpus-a",
        "/api/framework/corpus-a",
        "/api/profiles/corpus-a",
        "/api/superdocs/status",
        "/api/review/corpus-a",
    ]
    blob = ""
    for path in paths:
        blob += client.get(path).text
    lowered = blob.lower()
    for marker in SECRET_MARKERS:
        assert marker.lower() not in lowered
    assert "sk_live_should_never_appear" not in blob
    status = client.get("/api/superdocs/status").json()
    assert status["configured"] is True
    assert "api_key" not in json.dumps(status)


def test_superdocs_not_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    status = client.get("/api/superdocs/status").json()
    assert status["configured"] is False
    assert status["offline_demo"] is True
    assert status["live_export_available"] is False


def test_local_export_writes_artifact(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _analyze(client, "corpus-a")
    listing = client.get("/api/profiles/corpus-a").json()
    profile_id = listing["profiles"][0]["profile_id"]
    exported = client.post("/api/export/corpus-a", json={"kind": "profile", "profile_id": profile_id})
    assert exported.status_code == 200
    body = exported.json()
    assert body["ok"] is True
    assert Path(body["path"]).is_file()
    framework = client.post("/api/export/corpus-a", json={"kind": "framework"})
    assert Path(framework.json()["path"]).is_file()
    downloaded = client.get(f"/api/export/corpus-a/download/{framework.json()['filename']}")
    assert downloaded.status_code == 200
    missing = client.get("/api/export/corpus-a/download/not-real.docx")
    assert missing.status_code == 404
    traversal = client.get("/api/export/corpus-a/download/../secrets.docx")
    assert traversal.status_code in {400, 404}


def test_corpus_b_uses_same_backend_path(client: TestClient) -> None:
    payload = _analyze(client, "corpus-b")
    assert payload["organization"] == "Meridian HealthTech"
    assert payload["metrics"]["total_roles"] == 12
    roles = client.get("/api/architecture/corpus-b/roles").json()["roles"]
    assert len(roles) == 12
    framework = client.get("/api/framework/corpus-b")
    assert framework.status_code == 200
    exceptions = client.get("/api/exceptions/corpus-b").json()
    assert "misfit" in exceptions
