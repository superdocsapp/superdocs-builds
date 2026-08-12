"""
GET /negotiations/{id}/export, mocked via respx — no live SuperDocs call.
Goes through the real FastAPI app + router (not just the client method
directly) so the Content-Type / Content-Disposition headers are checked
end to end, since that's the actual point of this endpoint.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Negotiation
from app.routers.tracker import get_client
from app.superdocs_client import SuperDocsClient

BASE_URL = "https://api.superdocs.app"


@pytest.fixture
def db_session():
    # StaticPool + check_same_thread=False: TestClient dispatches the
    # endpoint on a different thread than this fixture runs on, and plain
    # sqlite:///:memory: ties its table-having connection to one thread.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def negotiation(db_session):
    neg = Negotiation(name="Test", superdocs_session_id="sess-1", cba_document_id="doc-1")
    db_session.add(neg)
    db_session.commit()
    db_session.refresh(neg)
    return neg


@pytest.fixture
def test_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_client] = lambda: SuperDocsClient(api_key="test-key", base_url=BASE_URL)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@respx.mock
def test_export_returns_docx_with_correct_content_type(test_client, negotiation):
    respx.post(f"{BASE_URL}/v1/documents/export").mock(
        return_value=httpx.Response(200, content=b"fake docx bytes")
    )

    response = test_client.get(f"/negotiations/{negotiation.id}/export")

    assert response.status_code == 200
    assert response.content == b"fake docx bytes"
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "agreement.docx" in response.headers["content-disposition"]


@respx.mock
def test_export_pdf_uses_pdf_content_type(test_client, negotiation):
    respx.post(f"{BASE_URL}/v1/documents/export").mock(return_value=httpx.Response(200, content=b"%PDF-fake"))

    response = test_client.get(f"/negotiations/{negotiation.id}/export", params={"format": "pdf"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_export_404_for_unknown_negotiation(test_client):
    response = test_client.get("/negotiations/does-not-exist/export")
    assert response.status_code == 404
