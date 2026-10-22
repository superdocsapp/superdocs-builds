import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.database import Base

# Ensure every model is registered on Base.metadata before create_all runs.
from app.domain import (  # noqa: F401,E402
    audit,
    bates,
    document,
    manifest,
    packet,
    page,
    privilege,
    redaction,
)

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet_test",
)


@pytest.fixture(scope="session")
def test_settings():
    return Settings(
        database_url=TEST_DATABASE_URL,
        superdocs_api_key="test-key",
        debug=True,
    )


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, checkfirst=True)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest.fixture(scope="function")
def mock_superdocs_adapter():
    from unittest.mock import AsyncMock, MagicMock

    from app.services.superdocs_port import (
        AttachmentUploadResult,
        DocumentUploadResult,
        JobStatus,
        ProposedChangeBatch,
        SuperDocsPort,
    )

    adapter = MagicMock(spec=SuperDocsPort)
    adapter.upload_document = AsyncMock(
        return_value=DocumentUploadResult(
            session_id="test-session",
            document_id="test-doc",
            chunks_count=10,
            version_id="v1",
            page_setup={},
            html="<html>Test</html>",
        )
    )
    adapter.upload_attachment = AsyncMock(
        return_value=AttachmentUploadResult(
            job_id="test-job",
            filename="test.pdf",
            status="processing",
        )
    )
    adapter.poll_job = AsyncMock(
        return_value=JobStatus(
            job_id="test-job",
            status="completed",
            result={
                "response": "Done",
                "document_changes": {"updated_html": "<html>Updated</html>"},
            },
        )
    )
    adapter.chat_async = AsyncMock(return_value="test-job")
    adapter.approve_changes = AsyncMock(
        return_value=JobStatus(
            job_id="test-job",
            status="completed",
        )
    )
    adapter.continue_job = AsyncMock(
        return_value=JobStatus(
            job_id="test-job",
            status="completed",
        )
    )
    adapter.export_document = AsyncMock(
        return_value=type(
            "ExportResult",
            (),
            {
                "download_url": "https://example.com/download",
                "filename": "export.pdf",
                "format": "pdf",
            },
        )()
    )
    adapter.get_session_history = AsyncMock(return_value={})
    adapter.parse_proposed_change_batch = MagicMock(
        return_value=ProposedChangeBatch(
            batch_id="batch-1",
            batch_total=1,
            changes=[],
        )
    )
    return adapter


@pytest.fixture(scope="function")
def fake_superdocs():
    from qa_helpers import FakeSuperDocsService

    return FakeSuperDocsService()


@pytest.fixture(scope="function")
def superdocs_override(api_client, fake_superdocs):
    """API client whose SuperDocs dependency AND background-task factories are
    wired to the in-memory fake engine.

    Yields (client, fake_service). The fake mirrors the SuperDocs API contract
    (detect_pii/apply_redactions/upload) against locally stored files, so the
    SuperDocs-native redaction paths run without a network.
    """
    return api_client, fake_superdocs


@pytest_asyncio.fixture(scope="function")
async def api_client(test_engine, monkeypatch, tmp_path, fake_superdocs):
    """HTTP client exercising the real FastAPI routers with an isolated DB,
    isolated storage root, and the in-memory SuperDocs fake. Background tasks
    (detect/processing) are redirected to the test database and the fake."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.api.redactions as redactions_module
    import app.workers.processor as processor_module
    from app.config import get_settings
    from app.database import get_session
    from app.main import app
    from app.services.redaction import RedactionApplicationService, RedactionDetectionService
    from app.services.superdocs_integration import get_superdocs_service

    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_superdocs_service] = lambda: fake_superdocs
    monkeypatch.setattr(
        redactions_module,
        "_new_detection_service",
        lambda: RedactionDetectionService(superdocs=fake_superdocs),
    )
    monkeypatch.setattr(
        redactions_module,
        "_new_application_service",
        lambda: RedactionApplicationService(superdocs=fake_superdocs),
    )
    monkeypatch.setattr(redactions_module, "async_session_maker", session_factory)
    monkeypatch.setattr(processor_module, "async_session_maker", session_factory)

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    settings.ensure_directories()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
