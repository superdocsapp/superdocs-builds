"""
The open-items tracker — the part the assignment card actually grades.
Mocked via respx, no live SuperDocs calls. Three things proven here:
  1. A chunk decided in round 1 and re-proposed in round 3 flips to
     REOPENED with round links updated, not silently left as round 1's
     OPEN item.
  2. reconcile() is idempotent — no duplicate OpenItem rows.
  3. If the local OpenItem table is wiped (but Negotiation/Round rows
     survive), reconcile() rebuilds a reasonable view from SuperDocs' own
     job history rather than crashing or returning nothing.
"""

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Negotiation, OpenItem, OpenItemStatus, Round, RoundStatus
from app.services import round_service, tracker_service
from app.superdocs_client import SuperDocsClient

BASE_URL = "https://api.superdocs.app"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def client():
    return SuperDocsClient(api_key="test-key", base_url=BASE_URL)


@pytest.fixture
def negotiation(db_session):
    neg = Negotiation(name="Test", superdocs_session_id="sess-1", cba_document_id="doc-1")
    db_session.add(neg)
    db_session.commit()
    db_session.refresh(neg)
    return neg


def _make_round(db_session, negotiation, number, job_id, status=RoundStatus.AWAITING_APPROVAL):
    round_ = Round(
        negotiation_id=negotiation.id,
        round_number=number,
        superdocs_job_id=job_id,
        status=status,
        prompt_used="test prompt",
    )
    db_session.add(round_)
    db_session.commit()
    db_session.refresh(round_)
    return round_


def _pending_response(chunk_id, old="a", new="b"):
    return httpx.Response(
        200,
        json={
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {"chunk_id": chunk_id, "change_id": f"change-{chunk_id}", "old_html": old, "new_html": new}
                ]
            },
        },
    )


def _mock_decide(job_id, chunk_id):
    # decide() fetches pending changes once (chunk_id -> change_id map,
    # live-confirmed 2026-08-12 the approve endpoint is change_id-keyed),
    # then polls the same job until it's no longer processing/awaiting
    respx.post(f"{BASE_URL}/v1/chat/sess-1/approve").mock(
        return_value=httpx.Response(200, json={"status": "ok", "batch_complete": True})
    )
    respx.get(f"{BASE_URL}/v1/jobs/{job_id}").mock(
        side_effect=[_pending_response(chunk_id), httpx.Response(200, json={"status": "completed"})]
    )


def test_reconcile_returns_empty_for_negotiation_with_no_rounds(db_session, client, negotiation):
    assert tracker_service.reconcile(db_session, client, negotiation.id) == []


def test_reconcile_raises_for_unknown_negotiation(db_session, client):
    with pytest.raises(ValueError):
        tracker_service.reconcile(db_session, client, "not-a-real-negotiation-id")


@respx.mock
def test_multi_round_reopen_flips_status_and_updates_round_links(db_session, client, negotiation):
    round_1 = _make_round(db_session, negotiation, 1, "job-1")
    respx.get(f"{BASE_URL}/v1/jobs/job-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-x", "content": {"old": "a", "new": "b"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_1.id)

    _mock_decide("job-1", "chunk-x")
    round_service.decide(db_session, client, round_1.id, [{"chunk_id": "chunk-x", "approved": True}])

    item = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="chunk-x").one()
    assert item.status == OpenItemStatus.APPROVED
    assert item.first_round_id == round_1.id
    assert item.last_round_id == round_1.id

    # round 2: unrelated chunk, doesn't touch chunk-x
    round_2 = _make_round(db_session, negotiation, 2, "job-2")
    respx.get(f"{BASE_URL}/v1/jobs/job-2").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-y", "content": {"old": "p", "new": "q"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_2.id)

    # round 3: re-proposes a change to chunk-x, previously APPROVED
    round_3 = _make_round(db_session, negotiation, 3, "job-3")
    respx.get(f"{BASE_URL}/v1/jobs/job-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-x", "content": {"old": "b", "new": "c"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_3.id)

    reconciled = tracker_service.reconcile(db_session, client, negotiation.id)
    by_chunk = {row["chunk_id"]: row for row in reconciled}

    assert by_chunk["chunk-x"]["status"] == OpenItemStatus.REOPENED
    assert by_chunk["chunk-x"]["first_round_id"] == round_1.id  # still round 1 — first raised there
    assert by_chunk["chunk-x"]["last_round_id"] == round_3.id  # updated to round 3 — reopened there
    assert by_chunk["chunk-y"]["status"] == OpenItemStatus.OPEN

    # no duplicate rows for chunk-x
    rows = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="chunk-x").all()
    assert len(rows) == 1


@respx.mock
def test_reconcile_is_idempotent(db_session, client, negotiation):
    round_1 = _make_round(db_session, negotiation, 1, "job-1")
    respx.get(f"{BASE_URL}/v1/jobs/job-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-x", "content": {"old": "a", "new": "b"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_1.id)

    first = tracker_service.reconcile(db_session, client, negotiation.id)
    second = tracker_service.reconcile(db_session, client, negotiation.id)

    assert first == second
    rows = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="chunk-x").all()
    assert len(rows) == 1


@respx.mock
def test_reconcile_rebuilds_from_job_history_after_local_wipe(db_session, client, negotiation):
    # populate via the normal write path first
    round_1 = _make_round(db_session, negotiation, 1, "job-1")
    respx.get(f"{BASE_URL}/v1/jobs/job-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-x", "content": {"old": "a", "new": "b"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_1.id)

    _mock_decide("job-1", "chunk-x")
    round_service.decide(db_session, client, round_1.id, [{"chunk_id": "chunk-x", "approved": True}])

    round_2 = _make_round(db_session, negotiation, 2, "job-2")
    respx.get(f"{BASE_URL}/v1/jobs/job-2").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "chunk-y", "content": {"old": "p", "new": "q"}}]},
            },
        )
    )
    round_service.list_pending_changes(db_session, client, round_2.id)

    assert db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id).count() == 2

    # simulate DB loss: wipe OpenItem rows only, Negotiation/Round rows survive
    db_session.query(OpenItem).delete()
    db_session.commit()
    assert db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id).count() == 0

    # GET /v1/sessions/{id}/jobs — shape live-confirmed 2026-08-12 (see
    # PROGRESS.md): {"jobs": [...], "total": N}, each entry the SAME shape
    # get_job returns. There's no separate "approve" job entry — a decided
    # job carries its outcome at result.document_changes.changes once
    # completed. Session only ever has ONE entry per job_id (its current
    # state), not one entry per status transition.
    respx.get(f"{BASE_URL}/v1/sessions/sess-1/jobs").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    # most recent first, per the API reference
                    {
                        "job_id": "job-2",
                        "status": "awaiting_approval",
                        "metadata": {
                            "pending_changes": [
                                {"chunk_id": "chunk-y", "old_html": "p", "new_html": "q"}
                            ]
                        },
                    },
                    {
                        "job_id": "job-1",
                        "status": "completed",
                        "metadata": {"pending_changes": []},
                        "result": {
                            "document_changes": {
                                "changes": [
                                    {"status": "approved", "chunk_id": "chunk-x", "new_html": "b"}
                                ]
                            }
                        },
                    },
                ],
                "total": 2,
            },
        )
    )

    reconciled = tracker_service.reconcile(db_session, client, negotiation.id)

    assert reconciled  # not empty — rebuilt something
    by_chunk = {row["chunk_id"]: row for row in reconciled}
    assert by_chunk["chunk-x"]["status"] == OpenItemStatus.APPROVED
    assert by_chunk["chunk-y"]["status"] == OpenItemStatus.OPEN
    # raised_by coming back "unknown" post-rebuild is honest and acceptable
    assert by_chunk["chunk-x"]["raised_by"] in ("unknown", "union", "employer")

    # calling again hits the fast local-rows path, still no duplicates
    again = tracker_service.reconcile(db_session, client, negotiation.id)
    assert again == reconciled
    assert db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id).count() == 2
