"""Backend tests. No API key, no network, no SuperDocs.

The important ones are the leak tests: GT-1 and GT-6 are asserted against the
real HTTP surface, not against a helper function, because the HTTP surface is
what a reviewer's browser can actually reach. A serializer that is safe in
isolation is worth nothing if some endpoint bypasses it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import corpus_builder as cb  # noqa: E402
from backend.assignment import (  # noqa: E402
    CONDITIONS,
    AssignmentError,
    build_assignments,
    check_balance,
    latin_square,
)
from backend.store import StudyStore  # noqa: E402
from corpus.edit_specs import DOC01  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "job_doc01.json"


def _confirmations(job: dict) -> dict:
    result = cb.match_changes_to_intents(cb.merge_changes([job]), DOC01.intents)
    return {
        lc.change.change_id: {
            "change_id": lc.change.change_id,
            "should_approve": lc.should_approve,
            "reason": lc.reason,
            "error_kind": lc.error_kind,
            "confirmed_by": "test-designer",
            "confirmed_at": "2026-08-14T10:00:00+00:00",
        }
        for lc in result.labelled
    }


@pytest.fixture
def study(tmp_path) -> StudyStore:
    """A two-batch corpus on disk, so the full 2x2 design is representable."""
    job = json.loads(FIXTURE.read_text(encoding="utf-8"))
    confirmations = _confirmations(job)

    batches = []
    for i in range(4):
        batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
        batch["batch_id"] = f"batch_doc{i:02d}"
        batch["document_id"] = f"doc{i:02d}"
        # DOC01 itself is withheld from the study, but these are stand-ins for
        # the four real study documents, so they must be servable.
        batch["exclude_from_study"] = False
        batches.append(batch)

    (tmp_path / "batches.json").write_text(
        json.dumps({"mode": "test", "batches": batches}), encoding="utf-8"
    )
    return StudyStore(
        batches_path=tmp_path / "batches.json",
        events_path=tmp_path / "raw_events.jsonl",
        assignment_path=tmp_path / "assignment.json",
    )


@pytest.fixture
def client(study, monkeypatch) -> TestClient:
    from backend import main

    monkeypatch.setattr(main, "store", study)
    return TestClient(main.app)


# -- assignment -----------------------------------------------------------


def test_latin_square_uses_each_item_once_per_position():
    square = latin_square(4)
    for position in range(4):
        column = [row[position] for row in square]
        assert sorted(column) == [0, 1, 2, 3], "each condition must occupy each slot once"


def test_reviewer_never_sees_the_same_batch_twice():
    """The core requirement: a repeated change is a contaminated measurement."""
    cells = build_assignments(["R1", "R2", "R3"], [f"b{i}" for i in range(4)])
    for reviewer in ("R1", "R2", "R3"):
        mine = [c for c in cells if c.reviewer_id == reviewer]
        assert len({c.batch_id for c in mine}) == len(mine)
        assert len({c.condition for c in mine}) == len(mine)


def test_condition_is_not_confounded_with_document():
    """A condition always paired with the same doc measures the doc, not the condition."""
    cells = build_assignments([f"R{i}" for i in range(4)], [f"b{i}" for i in range(4)])
    for condition in CONDITIONS:
        batches = {c.batch_id for c in cells if c.condition == condition}
        assert len(batches) > 1, f"{condition} only ever appeared on {batches}"


def test_full_panel_is_perfectly_balanced_across_positions():
    cells = build_assignments([f"R{i}" for i in range(4)], [f"b{i}" for i in range(4)])
    balance = check_balance(cells)
    for condition, positions in balance.items():
        assert set(positions.values()) == {1}, f"{condition} unbalanced: {positions}"


def test_too_few_batches_is_refused_by_default():
    with pytest.raises(AssignmentError, match="one batch per condition"):
        build_assignments(["R1"], ["b0", "b1"])


def test_pilot_may_opt_into_a_reduced_design():
    cells = build_assignments(["R1"], ["b0"], allow_partial=True)
    assert len(cells) == 1, "one batch supports exactly one condition per reviewer"


def test_empty_inputs_are_refused():
    with pytest.raises(AssignmentError):
        build_assignments([], ["b0"])
    with pytest.raises(AssignmentError):
        build_assignments(["R1"], [])


# -- GT-1 / GT-6 over HTTP ------------------------------------------------

FORBIDDEN_KEYS = {
    "ground_truth",
    "should_approve",
    "error_kind",
    "confirmed_by",
    "confirmed_at",
    "overrode_intent",
    "ground_truth_sha256",
    "source_change_id",
    "build_report",
    "seed",
    "pre_registered_at",
}


def _all_keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _all_keys(v)}
    if isinstance(obj, list):
        return {k for item in obj for k in _all_keys(item)}
    return set()


@pytest.mark.parametrize("condition", CONDITIONS)
def test_gt1_no_endpoint_leaks_ground_truth(client, study, condition):
    response = client.get("/api/batch/batch_doc00", params={"condition": condition})
    assert response.status_code == 200

    leaked = _all_keys(response.json()) & FORBIDDEN_KEYS
    assert not leaked, f"GT-1 leak over HTTP in {condition}: {leaked}"

    # and the rationales themselves must not appear anywhere in the body
    blob = response.text
    for record in study.raw_batch("batch_doc00")["ground_truth"]:
        assert record["reason"] not in blob


def test_gt1_holds_across_every_endpoint(client):
    """A whitelist on one serializer is worthless if another route bypasses it."""
    client.post("/api/session/start", json={"reviewer_id": "R1"})
    for path in ("/api/health", "/api/conditions", "/api/assignment", "/api/events/count"):
        leaked = _all_keys(client.get(path).json()) & FORBIDDEN_KEYS
        assert not leaked, f"GT-1 leak at {path}: {leaked}"


def test_gt6_recorded_event_contains_no_correctness(client, study):
    view = client.get("/api/batch/batch_doc00").json()
    change_id = view["changes"][0]["id"]

    response = client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": change_id,
            "decision": "approve",
            "shown_at": "2026-08-14T10:00:00+00:00",
            "decided_at": "2026-08-14T10:00:04+00:00",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision_ms"] == 4000

    event = study.read_events()[-1]
    assert not set(event) & FORBIDDEN_KEYS
    assert "correct" not in event and "is_error" not in event


# -- decision recording ---------------------------------------------------


def test_engagement_time_drives_decision_ms_not_render_time(client, study):
    """The run-1 artefact, asserted end to end (PROGRESS.md A18)."""
    view = client.get("/api/batch/batch_doc00").json()
    response = client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": view["changes"][0]["id"],
            "decision": "approve",
            # rendered with the batch, reached a minute later, decided 3s after that
            "shown_at": "2026-08-14T10:00:00+00:00",
            "engaged_at": "2026-08-14T10:01:00+00:00",
            "decided_at": "2026-08-14T10:01:03+00:00",
        },
    )
    assert response.status_code == 200
    assert response.json()["decision_ms"] == 3000, "must not charge the 60s wait"

    event = study.read_events()[-1]
    assert event["decision_ms"] == 3000
    assert event["render_to_decision_ms"] == 63000, "the batch-level measure is kept"
    assert event["was_engaged"] is True


def test_missing_engagement_falls_back_to_render_and_is_flagged(client, study):
    view = client.get("/api/batch/batch_doc00").json()
    client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": view["changes"][0]["id"],
            "decision": "reject",
            "shown_at": "2026-08-14T10:00:00+00:00",
            "decided_at": "2026-08-14T10:00:05+00:00",
        },
    )
    event = study.read_events()[-1]
    assert event["decision_ms"] == 5000
    assert event["engaged_at"] == event["shown_at"]
    assert event["was_engaged"] is False, "the fallback must be visible in the data"


def test_decision_timing_is_recorded_in_milliseconds(client, study):
    view = client.get("/api/batch/batch_doc00").json()
    client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "sequential_whole",
            "reviewer_change_id": view["changes"][1]["id"],
            "decision": "reject",
            "shown_at": "2026-08-14T10:00:00+00:00",
            "decided_at": "2026-08-14T10:00:12.500000+00:00",
        },
    )
    assert study.read_events()[-1]["decision_ms"] == 12500


def test_unknown_change_id_is_rejected_not_stored(client, study):
    """An event that joins to nothing would silently vanish from the results."""
    before = len(study.read_events())
    response = client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": "deadbeefcafe",
            "decision": "approve",
            "shown_at": "2026-08-14T10:00:00+00:00",
            "decided_at": "2026-08-14T10:00:01+00:00",
        },
    )
    assert response.status_code == 400
    assert len(study.read_events()) == before


def test_invalid_decision_verb_is_rejected(client):
    view = client.get("/api/batch/batch_doc00").json()
    response = client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": view["changes"][0]["id"],
            "decision": "maybe",
            "shown_at": "2026-08-14T10:00:00+00:00",
            "decided_at": "2026-08-14T10:00:01+00:00",
        },
    )
    assert response.status_code == 400


def test_unknown_condition_is_rejected(client):
    assert client.get("/api/batch/batch_doc00", params={"condition": "nope"}).status_code == 400


def test_unknown_batch_is_404(client):
    assert client.get("/api/batch/no_such_batch").status_code == 404


def test_events_are_append_only(client, study):
    view = client.get("/api/batch/batch_doc00").json()
    for change in view["changes"][:3]:
        client.post(
            "/api/decision",
            json={
                "reviewer_id": "R1",
                "batch_id": "batch_doc00",
                "condition": "batch_section",
                "reviewer_change_id": change["id"],
                "decision": "approve",
                "shown_at": "2026-08-14T10:00:00+00:00",
                "decided_at": "2026-08-14T10:00:02+00:00",
            },
        )
    assert len(study.read_events()) == 3

    # A reviewer changing their mind appends; it never rewrites history.
    client.post(
        "/api/decision",
        json={
            "reviewer_id": "R1",
            "batch_id": "batch_doc00",
            "condition": "batch_section",
            "reviewer_change_id": view["changes"][0]["id"],
            "decision": "reject",
            "shown_at": "2026-08-14T10:00:10+00:00",
            "decided_at": "2026-08-14T10:00:14+00:00",
        },
    )
    events = study.read_events()
    assert len(events) == 4
    assert events[0]["decision"] == "approve" and events[-1]["decision"] == "reject"


# -- session --------------------------------------------------------------


def test_session_start_returns_a_stable_order(client):
    first = client.post("/api/session/start", json={"reviewer_id": "R1"}).json()
    second = client.post("/api/session/start", json={"reviewer_id": "R1"}).json()
    assert first["assignment"] == second["assignment"], (
        "a reviewer who reloads must resume the same order, not be re-randomised"
    )
    assert len(first["assignment"]) == len(CONDITIONS)


def test_second_reviewer_gets_a_different_order(client):
    first = client.post("/api/session/start", json={"reviewer_id": "R1"}).json()
    second = client.post("/api/session/start", json={"reviewer_id": "R2"}).json()
    orders = (
        [e["condition"] for e in first["assignment"]],
        [e["condition"] for e in second["assignment"]],
    )
    assert orders[0] != orders[1], "counterbalancing requires different running orders"


def test_condition_carries_presentation_and_granularity(client):
    body = client.get("/api/batch/batch_doc00", params={"condition": "sequential_whole"}).json()
    assert body["presentation"] == "sequential"
    assert body["granularity"] == "whole"


def test_health_reports_loaded_batches(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "batch_doc00" in body["batches"]


def test_excluded_batches_are_never_assignable_or_servable(tmp_path):
    """A batch whose answers the reviewer has seen must not reach them."""
    job = json.loads(FIXTURE.read_text(encoding="utf-8"))
    confirmations = _confirmations(job)

    served = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
    served["batch_id"] = "batch_ok"
    served["exclude_from_study"] = False

    withheld = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
    withheld["batch_id"] = "batch_seen_by_reviewer"
    withheld["exclude_from_study"] = True

    path = tmp_path / "batches.json"
    path.write_text(json.dumps({"batches": [served, withheld]}), encoding="utf-8")

    store = StudyStore(
        batches_path=path,
        events_path=tmp_path / "e.jsonl",
        assignment_path=tmp_path / "a.json",
    )

    assert store.batch_ids == ["batch_ok"]
    assert store.excluded_batch_ids == ["batch_seen_by_reviewer"]
    assert store.reviewer_view("batch_seen_by_reviewer") is None
    assert store.change_ids_for("batch_seen_by_reviewer") == set()


# -- store ----------------------------------------------------------------


def test_store_refuses_a_corpus_whose_answer_key_drifted(tmp_path):
    """GT-4 at startup: fail loudly rather than collect data against a bad key."""
    from ground_truth import GroundTruthTampered

    job = json.loads(FIXTURE.read_text(encoding="utf-8"))
    batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=_confirmations(job))
    batch["ground_truth"][0]["should_approve"] = not batch["ground_truth"][0]["should_approve"]

    path = tmp_path / "batches.json"
    path.write_text(json.dumps({"batches": [batch]}), encoding="utf-8")

    with pytest.raises(GroundTruthTampered):
        StudyStore(batches_path=path, events_path=tmp_path / "e.jsonl",
                   assignment_path=tmp_path / "a.json")
