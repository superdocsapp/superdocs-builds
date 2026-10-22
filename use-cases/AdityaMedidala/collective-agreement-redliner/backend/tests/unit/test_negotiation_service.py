"""
start_negotiation, mocked all the way down: httpx is intercepted via respx
so no live SuperDocs call happens, per CLAUDE.md rule 3.
"""

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.services import negotiation_service, polling
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


@respx.mock
def test_start_negotiation_end_to_end(db_session, client, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    respx.post(f"{BASE_URL}/v1/documents/upload-base64").mock(
        return_value=httpx.Response(200, json={"document_id": "doc-1"})
    )
    respx.post(f"{BASE_URL}/v1/attachments/upload-base64").mock(
        side_effect=[
            httpx.Response(200, json={"job_id": "job-union"}),
            httpx.Response(200, json={"job_id": "job-employer"}),
        ]
    )
    respx.get(f"{BASE_URL}/v1/jobs/job-union").mock(
        return_value=httpx.Response(200, json={"status": "completed", "result": {"attachment_id": "att-union"}})
    )
    respx.get(f"{BASE_URL}/v1/jobs/job-employer").mock(
        return_value=httpx.Response(
            200, json={"status": "completed", "result": {"attachment_id": "att-employer"}}
        )
    )

    negotiation = negotiation_service.start_negotiation(
        db_session, client, "Test CBA", b"cba bytes", b"union bytes", b"employer bytes"
    )

    assert negotiation.id
    assert negotiation.name == "Test CBA"
    assert negotiation.cba_document_id == "doc-1"
    assert negotiation.union_attachment_id == "att-union"
    assert negotiation.employer_attachment_id == "att-employer"
    assert negotiation.superdocs_session_id  # generated uuid, non-empty

    # row is actually persisted, not just returned in memory
    persisted = db_session.get(type(negotiation), negotiation.id)
    assert persisted is not None
    assert persisted.superdocs_session_id == negotiation.superdocs_session_id


@respx.mock
def test_start_negotiation_polls_attachment_jobs_until_completed(db_session, client, monkeypatch):
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)

    respx.post(f"{BASE_URL}/v1/documents/upload-base64").mock(
        return_value=httpx.Response(200, json={"document_id": "doc-1"})
    )
    respx.post(f"{BASE_URL}/v1/attachments/upload-base64").mock(
        side_effect=[
            httpx.Response(200, json={"job_id": "job-union"}),
            httpx.Response(200, json={"job_id": "job-employer"}),
        ]
    )
    union_route = respx.get(f"{BASE_URL}/v1/jobs/job-union")
    union_route.mock(
        side_effect=[
            httpx.Response(200, json={"status": "pending"}),
            httpx.Response(200, json={"status": "processing"}),
            httpx.Response(200, json={"status": "completed", "result": {"attachment_id": "att-union"}}),
        ]
    )
    respx.get(f"{BASE_URL}/v1/jobs/job-employer").mock(
        return_value=httpx.Response(200, json={"status": "completed", "result": {"attachment_id": "att-employer"}})
    )

    negotiation = negotiation_service.start_negotiation(
        db_session, client, "Test CBA", b"cba", b"union", b"employer"
    )

    assert negotiation.union_attachment_id == "att-union"
    assert union_route.call_count == 3  # stopped as soon as status left pending/processing
