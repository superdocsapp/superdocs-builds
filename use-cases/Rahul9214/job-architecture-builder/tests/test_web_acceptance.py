"""Offline reviewer acceptance path. No live SuperDocs."""

from __future__ import annotations

from fastapi.testclient import TestClient

from job_architecture.web.app import create_app
from job_architecture.web.service import WorkspaceService
from job_architecture.web.store import WorkspaceStore


def _client() -> TestClient:
    return TestClient(create_app(WorkspaceService(WorkspaceStore())))


def test_northstar_offline_acceptance_path() -> None:
    client = _client()
    analyzed = client.post("/api/corpora/corpus-a/analyze")
    assert analyzed.status_code == 200
    architecture = client.get("/api/architecture/corpus-a").json()
    assert architecture["metrics"]["total_roles"] == 21
    assert architecture["clusters"]

    exceptions = client.get("/api/exceptions/corpus-a").json()
    assert exceptions["provisional"] or exceptions["misfit"]
    sample = (exceptions["misfit"] or exceptions["provisional"])[0]
    assert sample["why"]
    if sample["bucket"] == "misfit":
        assert sample["status"] == "requires_architecture_decision"

    profiles = client.get("/api/profiles/corpus-a").json()["profiles"]
    ic4 = next(item for item in profiles if item["level_label"] == "IC4")
    detail = client.get(f"/api/profiles/corpus-a/{ic4['profile_id']}").json()
    assert "IC4" in detail["level_expectations"]
    original_purpose = detail["role_purpose"]

    planned = client.post(
        "/api/updates/corpus-a/plan",
        json={
            "level_id": "ic4",
            "dimension": "scope",
            "value": "Cross-team domain plus an explicit sequencing veto for live verification.",
        },
    )
    assert planned.status_code == 200
    impact = planned.json()["impact"]
    assert impact["affected_profiles_count"] >= 1
    assert impact["unaffected_profiles_count"] >= 1
    plans = planned.json()["plans"]
    assert plans
    assert all(item["section_id"] == "level_expectations" for item in plans)

    items = [{"plan_id": item["plan_id"], "approved": True} for item in plans]
    client.post("/api/review/corpus-a/decisions", json={"items": items})
    applied = client.post("/api/review/corpus-a/apply").json()
    assert applied["domain_applied"] is True
    assert applied["preservation"]["ok"] is True
    refreshed = client.get(f"/api/profiles/corpus-a/{ic4['profile_id']}").json()
    assert "sequencing veto" in refreshed["level_expectations"].lower()
    assert refreshed["role_purpose"] == original_purpose


def test_corpus_b_smoke_path() -> None:
    client = _client()
    analyzed = client.post("/api/corpora/corpus-b/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["organization"] == "Meridian HealthTech"
    architecture = client.get("/api/architecture/corpus-b")
    assert architecture.status_code == 200
    exceptions = client.get("/api/exceptions/corpus-b")
    assert exceptions.status_code == 200
    framework = client.get("/api/framework/corpus-b")
    assert framework.status_code == 200
    profiles = client.get("/api/profiles/corpus-b")
    assert profiles.status_code == 200
    impact = client.post(
        "/api/impact/corpus-b/level-change",
        json={"dimension": "scope", "value": "Added Meridian reviewer scope note."},
    )
    assert impact.status_code == 200
