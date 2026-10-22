import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.superdocs_integration import SuperDocsIntegrationService
from app.services.superdocs_port import (
    DocumentUploadResult,
    JobStatus,
    ProposedChangeBatch,
    ExportResult,
)
from app.domain.document import Document, ProcessingStatus


class TestSuperDocsIntegrationService:
    @pytest.fixture
    def mock_adapter(self):
        adapter = MagicMock()
        adapter.upload_document = AsyncMock(return_value=DocumentUploadResult(
            session_id="test-session",
            document_id="test-doc",
            chunks_count=10,
            version_id="v1",
            page_setup={},
            html="<html>Test</html>",
        ))
        adapter.chat_async = AsyncMock(return_value="test-job")
        adapter.poll_job = AsyncMock(return_value=JobStatus(
            job_id="test-job",
            status="completed",
            result={"response": "Done", "document_changes": {"updated_html": "<html>Updated</html>"}},
            metadata=None,
        ))
        adapter.approve_changes = AsyncMock(return_value=JobStatus(
            job_id="test-job",
            status="completed",
            result={"response": "Done"},
        ))
        adapter.continue_job = AsyncMock(return_value=JobStatus(
            job_id="test-job",
            status="completed",
        ))
        adapter.export_document = AsyncMock(return_value=ExportResult(
            download_url="https://example.com/download",
            filename="export.pdf",
            format="pdf",
        ))
        adapter.get_session_history = AsyncMock(return_value={"messages": []})
        adapter.parse_proposed_change_batch = MagicMock(return_value=ProposedChangeBatch(
            batch_id="batch-1",
            batch_total=1,
            changes=[],
            awaiting_kind="approval",
        ))
        adapter.close = AsyncMock()
        return adapter

    @pytest.fixture
    def service(self, mock_adapter):
        return SuperDocsIntegrationService(adapter=mock_adapter)

    @pytest.fixture
    def sample_document(self):
        return Document(
            id="00000000-0000-0000-0000-000000000001",
            packet_id="00000000-0000-0000-0000-000000000002",
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="a" * 64,
            document_type="pdf",
            page_count=5,
            processing_status=ProcessingStatus.COMPLETED,
            original_sha256="a" * 64,
        )

    @pytest.mark.asyncio
    async def test_upload_document_to_superdocs(self, mock_adapter, sample_document, tmp_path):
        from app.config import Settings
        test_file = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pdf"
        test_file.write_bytes(b"%PDF-1.4 test")

        test_settings = Settings(
            originals_dir="",
            storage_root=tmp_path,
        )
        service = SuperDocsIntegrationService(adapter=mock_adapter, settings=test_settings)

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        result = await service.upload_document_to_superdocs(mock_session, sample_document)

        assert result.session_id == "test-session"
        assert result.document_id == "test-doc"
        assert sample_document.superdocs_session_id == "test-session"
        assert sample_document.superdocs_document_id == "test-doc"

    @pytest.mark.asyncio
    async def test_upload_document_already_uploaded(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "existing-session"
        sample_document.superdocs_document_id = "existing-doc"

        result = await service.upload_document_to_superdocs(None, sample_document)

        assert result.session_id == "existing-session"
        assert result.document_id == "existing-doc"
        mock_adapter.upload_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_ai_analysis(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "test-session"
        sample_document.superdocs_document_id = "test-doc"

        job_id = await service.request_ai_analysis(
            session=None,
            document=sample_document,
            instruction="Summarize this document",
        )

        assert job_id == "test-job"
        mock_adapter.chat_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_poll_ai_job(self, service, mock_adapter):
        job_status = await service.poll_ai_job("test-job")

        assert job_status.job_id == "test-job"
        assert job_status.status == "completed"
        mock_adapter.poll_job.assert_called_once_with("test-job")

    @pytest.mark.asyncio
    async def test_get_proposed_changes_awaiting_approval(self, service, mock_adapter):
        mock_adapter.poll_job.return_value = JobStatus(
            job_id="test-job",
            status="awaiting_approval",
            metadata={"pending_changes": "test content"},
        )

        changes = await service.get_proposed_changes("test-job")

        assert isinstance(changes, ProposedChangeBatch)
        mock_adapter.parse_proposed_change_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_proposed_changes_not_awaiting(self, service, mock_adapter):
        mock_adapter.poll_job.return_value = JobStatus(
            job_id="test-job",
            status="completed",
            metadata=None,
        )

        changes = await service.get_proposed_changes("test-job")

        assert changes.batch_total == 0
        assert len(changes.changes) == 0

    @pytest.mark.asyncio
    async def test_approve_changes(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "test-session"

        result = await service.approve_changes(
            document=sample_document,
            job_id="test-job",
            approved=True,
            changes=[{"change_id": "ch_1"}],
        )

        assert result.status == "completed"
        mock_adapter.approve_changes.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_changes_no_session(self, service, sample_document):
        with pytest.raises(ValueError, match="Document not uploaded to SuperDocs"):
            await service.approve_changes(
                document=sample_document,
                job_id="test-job",
                approved=True,
                changes=[],
            )

    @pytest.mark.asyncio
    async def test_continue_job(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "test-session"

        result = await service.continue_job(
            document=sample_document,
            job_id="test-job",
            continue_job=True,
        )

        assert result.status == "completed"
        mock_adapter.continue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_document(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "test-session"

        result = await service.export_document(
            document=sample_document,
            format="pdf",
        )

        assert result.download_url == "https://example.com/download"
        assert result.format == "pdf"
        mock_adapter.export_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_history(self, service, mock_adapter, sample_document):
        sample_document.superdocs_session_id = "test-session"

        result = await service.get_session_history(sample_document)

        assert result == {"messages": []}
        mock_adapter.get_session_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, service, mock_adapter):
        await service.close()
        mock_adapter.close.assert_called_once()