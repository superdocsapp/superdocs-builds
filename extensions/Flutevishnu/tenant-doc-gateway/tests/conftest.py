"""Shared pytest fixtures.

The test DB is a real on-disk SQLite file (not :memory:) so that multiple async
connections — required by the CONCURRENT idempotency test — see the same data and
the UNIQUE constraint can actually arbitrate races.

Environment is configured BEFORE importing app modules so pydantic-settings picks
up the test values, and the settings cache is cleared to be safe.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

# --- Configure environment before importing the app ---
_TMPDIR = tempfile.mkdtemp(prefix="tdg_test_")
_DB_PATH = os.path.join(_TMPDIR, "test.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["UPLOAD_DIR"] = os.path.join(_TMPDIR, "uploads")
os.environ["WEBHOOK_SIGNING_SECRET"] = "test-webhook-secret"
os.environ["SUPERDOCS_API_KEY"] = "unused-because-mocked"
os.environ["SAMPLE_MODE"] = "true"

import httpx  # noqa: E402
from httpx import ASGITransport  # noqa: E402

from app.api.deps import get_superdocs_client  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_sessionmaker, reset_engine_state  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.queue import get_job_queue  # noqa: E402
from tests.fakes import FakeQueue, FakeSuperDocsClient  # noqa: E402

get_settings.cache_clear()
reset_engine_state()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def sessionmaker():
    return get_sessionmaker()


@pytest.fixture
def fake_superdocs() -> FakeSuperDocsClient:
    return FakeSuperDocsClient()


@pytest.fixture
def queue_recorder() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def app(fake_superdocs: FakeSuperDocsClient, queue_recorder: FakeQueue):
    application = create_app()
    application.dependency_overrides[get_job_queue] = lambda: queue_recorder
    application.dependency_overrides[get_superdocs_client] = lambda: fake_superdocs
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def make_tenant(client: httpx.AsyncClient):
    """Create a tenant via the admin API; returns (tenant_id, auth_headers)."""

    async def _make(name: str | None = None) -> tuple[str, dict]:
        resp = await client.post(
            "/v1/admin/tenants",
            json={"name": name or f"tenant-{uuid.uuid4().hex[:6]}"},
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return data["tenant_id"], {"Authorization": f"Bearer {data['api_key']}"}

    return _make


@pytest_asyncio.fixture
async def ready_document(client, make_tenant, fake_superdocs, sessionmaker, settings):
    """A tenant with an uploaded document that has been processed to READY.

    Drives the upload job through the real job_runner with the fake SuperDocs
    client, mirroring what the Arq worker does in production.
    """
    from app.services.job_runner import run_job

    tenant_id, headers = await make_tenant()
    files = {"file": ("contract.docx", b"synthetic fictional document body", "application/octet-stream")}
    resp = await client.post(
        "/v1/documents",
        files=files,
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 202, resp.text
    document_id = resp.json()["document"]["id"]
    job_id = resp.json()["job"]["job_id"]

    await run_job(
        uuid.UUID(job_id),
        sessionmaker=sessionmaker,
        superdocs=fake_superdocs,
        settings=settings,
        poll_interval=0,
    )
    return tenant_id, headers, document_id
