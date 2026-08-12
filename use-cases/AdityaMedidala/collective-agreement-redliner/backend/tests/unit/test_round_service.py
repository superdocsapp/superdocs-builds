"""
start_round + list_pending_changes, mocked all the way down via respx.
The polling-loop-stops test guards against the routing bug Task 1 hit
more than once: a poll loop stuck because the stop condition never fires.
"""

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Negotiation, OpenItem, OpenItemStatus, Round, RoundStatus
from app.services import polling, round_service
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


@respx.mock
def test_start_round_polling_stops_once_status_changes(db_session, client, negotiation, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    respx.post(f"{BASE_URL}/v1/chat/async").mock(return_value=httpx.Response(200, json={"job_id": "job-1"}))
    job_route = respx.get(f"{BASE_URL}/v1/jobs/job-1")
    job_route.mock(
        side_effect=[
            httpx.Response(200, json={"status": "pending"}),
            httpx.Response(200, json={"status": "processing"}),
            httpx.Response(200, json={"status": "awaiting_approval", "metadata": {"pending_changes": []}}),
        ]
    )

    round_ = round_service.start_round(db_session, client, negotiation.id)

    assert round_.status == RoundStatus.AWAITING_APPROVAL
    assert round_.superdocs_job_id == "job-1"
    assert round_.round_number == 1
    # exactly 3 polls, not stuck looping past the status change
    assert job_route.call_count == 3


@respx.mock
def test_start_round_stops_polling_after_max_attempts(db_session, client, negotiation, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    respx.post(f"{BASE_URL}/v1/chat/async").mock(return_value=httpx.Response(200, json={"job_id": "job-2"}))
    job_route = respx.get(f"{BASE_URL}/v1/jobs/job-2")
    job_route.mock(return_value=httpx.Response(200, json={"status": "pending"}))

    round_ = round_service.start_round(db_session, client, negotiation.id, prompt="custom prompt")

    # a job stuck forever on "pending" must not hang the poller
    assert job_route.call_count == 30
    assert round_.status == RoundStatus.FAILED
    assert round_.prompt_used == "custom prompt"


@pytest.fixture
def awaiting_round(db_session, negotiation):
    round_ = Round(
        negotiation_id=negotiation.id,
        round_number=1,
        superdocs_job_id="job-decide",
        status=RoundStatus.AWAITING_APPROVAL,
        prompt_used="test prompt",
    )
    db_session.add(round_)
    db_session.commit()
    db_session.refresh(round_)
    return round_


def _pending_changes_response(*chunk_ids):
    return httpx.Response(
        200,
        json={
            "status": "awaiting_approval",
            "metadata": {
                "pending_changes": [
                    {"chunk_id": chunk_id, "change_id": f"change-{chunk_id}"} for chunk_id in chunk_ids
                ]
            },
        },
    )


@respx.mock
def test_decide_polling_stops_once_status_changes(db_session, client, awaiting_round, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    approve_route = respx.post(f"{BASE_URL}/v1/chat/sess-1/approve").mock(
        return_value=httpx.Response(200, json={"status": "ok", "batch_complete": True})
    )
    # decide() fetches pending changes once to map chunk_id -> change_id
    # (the live approve endpoint is change_id-keyed, confirmed 2026-08-12),
    # then poll_job re-checks the same job until it leaves "processing"
    responses = [_pending_changes_response("c1"), httpx.Response(200, json={"status": "processing"}),
                 httpx.Response(200, json={"status": "completed"})]
    job_route = respx.get(f"{BASE_URL}/v1/jobs/job-decide")
    job_route.side_effect = responses

    decisions = [{"chunk_id": "c1", "approved": True, "feedback": None}]
    round_ = round_service.decide(db_session, client, awaiting_round.id, decisions)

    assert approve_route.call_count == 1
    assert round_.status == RoundStatus.COMPLETED
    # 1 fetch for the chunk_id->change_id map + exactly 2 polls, not stuck
    # looping past the status change
    assert job_route.call_count == 3


@respx.mock
def test_decide_stops_polling_after_max_attempts(db_session, client, awaiting_round, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    respx.post(f"{BASE_URL}/v1/chat/sess-1/approve").mock(
        return_value=httpx.Response(200, json={"status": "ok", "batch_complete": False})
    )
    job_route = respx.get(f"{BASE_URL}/v1/jobs/job-decide")

    call_count = {"n": 0}

    def responder(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _pending_changes_response("c1")
        return httpx.Response(200, json={"status": "processing"})

    job_route.side_effect = responder

    round_ = round_service.decide(db_session, client, awaiting_round.id, [{"chunk_id": "c1", "approved": True}])

    # a decision job stuck forever on "processing" must not hang the poller:
    # 1 map fetch + 30 bounded poll attempts
    assert job_route.call_count == 31
    assert round_.status == RoundStatus.FAILED


def test_decide_raises_for_unknown_round(db_session, client):
    with pytest.raises(ValueError):
        round_service.decide(db_session, client, "not-a-real-round-id", [])


@pytest.fixture
def pending_round(db_session, negotiation):
    round_ = Round(
        negotiation_id=negotiation.id,
        round_number=1,
        superdocs_job_id="job-3",
        status=RoundStatus.AWAITING_APPROVAL,
        prompt_used="test prompt",
    )
    db_session.add(round_)
    db_session.commit()
    db_session.refresh(round_)
    return round_


@respx.mock
def test_list_pending_changes_double_parses_content(db_session, client, pending_round):
    respx.get(f"{BASE_URL}/v1/jobs/job-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [{"chunk_id": "c1", "content": '{"old": "a", "new": "b"}'}]
                },
            },
        )
    )

    changes = round_service.list_pending_changes(db_session, client, pending_round.id)

    assert changes[0]["chunk_id"] == "c1"
    assert changes[0]["content"] == {"old": "a", "new": "b"}


def test_list_pending_changes_raises_for_unknown_round(db_session, client):
    with pytest.raises(ValueError):
        round_service.list_pending_changes(db_session, client, "not-a-real-round-id")


@respx.mock
def test_list_pending_changes_creates_open_item(db_session, client, negotiation, pending_round):
    respx.get(f"{BASE_URL}/v1/jobs/job-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "c1", "content": {"old": "a", "new": "b"}}]},
            },
        )
    )

    round_service.list_pending_changes(db_session, client, pending_round.id)

    item = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="c1").one()
    assert item.status == OpenItemStatus.OPEN
    assert item.first_round_id == pending_round.id
    assert item.last_round_id == pending_round.id


@respx.mock
def test_reproposing_a_decided_chunk_reopens_it(db_session, client, negotiation, pending_round):
    # simulate round 1 already having decided chunk c1 (approved)
    decided = OpenItem(
        negotiation_id=negotiation.id,
        chunk_id="c1",
        status=OpenItemStatus.APPROVED,
        raised_by="union",
        first_round_id=pending_round.id,
        last_round_id=pending_round.id,
    )
    db_session.add(decided)
    db_session.commit()

    round_3 = Round(
        negotiation_id=negotiation.id,
        round_number=3,
        superdocs_job_id="job-round-3",
        status=RoundStatus.AWAITING_APPROVAL,
        prompt_used="test prompt",
    )
    db_session.add(round_3)
    db_session.commit()
    db_session.refresh(round_3)

    respx.get(f"{BASE_URL}/v1/jobs/job-round-3").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "awaiting_approval",
                "metadata": {"pending_changes": [{"chunk_id": "c1", "content": {"old": "b", "new": "c"}}]},
            },
        )
    )

    round_service.list_pending_changes(db_session, client, round_3.id)

    item = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="c1").one()
    assert item.status == OpenItemStatus.REOPENED
    assert item.first_round_id == pending_round.id  # unchanged — still the round that first raised it
    assert item.last_round_id == round_3.id  # updated to the round that reopened it


@respx.mock
def test_decide_upserts_approved_and_rejected_items(db_session, client, negotiation, awaiting_round):
    approve_route = respx.post(f"{BASE_URL}/v1/chat/sess-1/approve").mock(
        return_value=httpx.Response(200, json={"status": "ok", "batch_complete": True})
    )
    job_route = respx.get(f"{BASE_URL}/v1/jobs/job-decide")
    job_route.side_effect = [
        _pending_changes_response("c1", "c2"),
        httpx.Response(200, json={"status": "completed"}),
    ]

    decisions = [
        {"chunk_id": "c1", "approved": True, "feedback": None},
        {"chunk_id": "c2", "approved": False, "feedback": "not yet"},
    ]
    round_service.decide(db_session, client, awaiting_round.id, decisions)

    # one approve_change call per decision — the live endpoint is
    # single-decision-per-call, not the batch shape docs described
    assert approve_route.call_count == 2

    approved = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="c1").one()
    rejected = db_session.query(OpenItem).filter_by(negotiation_id=negotiation.id, chunk_id="c2").one()
    assert approved.status == OpenItemStatus.APPROVED
    assert rejected.status == OpenItemStatus.REJECTED
    assert approved.last_round_id == awaiting_round.id
    assert rejected.last_round_id == awaiting_round.id
