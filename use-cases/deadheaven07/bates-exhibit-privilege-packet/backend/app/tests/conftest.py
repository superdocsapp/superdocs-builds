import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.database import Base
from app.config import Settings

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


TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet"


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
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.fixture(scope="function")
def mock_superdocs_adapter():
    from unittest.mock import AsyncMock, MagicMock
    from app.services.superdocs_port import (
        SuperDocsPort,
        DocumentUploadResult,
        AttachmentUploadResult,
        JobStatus,
        ProposedChangeBatch,
    )

    adapter = MagicMock(spec=SuperDocsPort)
    adapter.upload_document = AsyncMock(return_value=DocumentUploadResult(
        session_id="test-session",
        document_id="test-doc",
        chunks_count=10,
        version_id="v1",
        page_setup={},
        html="<html>Test</html>",
    ))
    adapter.upload_attachment = AsyncMock(return_value=AttachmentUploadResult(
        job_id="test-job",
        filename="test.pdf",
        status="processing",
    ))
    adapter.poll_job = AsyncMock(return_value=JobStatus(
        job_id="test-job",
        status="completed",
        result={"response": "Done", "document_changes": {"updated_html": "<html>Updated</html>"}},
    ))
    adapter.chat_async = AsyncMock(return_value="test-job")
    adapter.approve_changes = AsyncMock(return_value=JobStatus(
        job_id="test-job",
        status="completed",
    ))
    adapter.continue_job = AsyncMock(return_value=JobStatus(
        job_id="test-job",
        status="completed",
    ))
    adapter.export_document = AsyncMock(return_value=type('ExportResult', (), {
        'download_url': 'https://example.com/download',
        'filename': 'export.pdf',
        'format': 'pdf',
    })())
    adapter.get_session_history = AsyncMock(return_value={})
    adapter.parse_proposed_change_batch = MagicMock(return_value=ProposedChangeBatch(
        batch_id="batch-1",
        batch_total=1,
        changes=[],
    ))
    return adapter


@pytest_asyncio.fixture(scope="function")
async def api_client(test_engine, monkeypatch, tmp_path):
    """HTTP client exercising the real FastAPI routers with an isolated DB and
    storage root. Background tasks (detect/processing) are redirected to the
    test database."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from app.database import get_session
    from app.config import get_settings
    from app.main import app
    import app.api.redactions as redactions_module
    import app.workers.processor as processor_module

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr(redactions_module, "async_session_maker", session_factory)
    monkeypatch.setattr(processor_module, "async_session_maker", session_factory)

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    settings.ensure_directories()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()