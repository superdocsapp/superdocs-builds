from io import BytesIO
from unittest.mock import patch

import pytest

from app.domain.document import DocumentType
from app.services.ingestion import FileValidationError, IngestionService


class TestIngestionService:
    @pytest.fixture
    def service(self):
        return IngestionService()

    @pytest.fixture
    def sample_pdf_bytes(self):
        return b"%PDF-1.4\n%Test PDF content\n%%EOF"

    @pytest.fixture
    def sample_docx_bytes(self):
        return b"PK\x03\x04" + b"x" * 100

    @pytest.fixture
    def sample_image_bytes(self):
        import io

        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        return img_bytes.getvalue()

    def test_validate_file_supported_pdf(self, service, sample_pdf_bytes):
        file_stream = BytesIO(sample_pdf_bytes)
        mime_type, file_size = service.validate_file(file_stream, "test.pdf")
        assert mime_type == "application/pdf"
        assert file_size == len(sample_pdf_bytes)

    def test_validate_file_supported_image(self, service, sample_image_bytes):
        file_stream = BytesIO(sample_image_bytes)
        mime_type, file_size = service.validate_file(file_stream, "test.png")
        assert mime_type == "image/png"

    def test_validate_file_unsupported_type(self, service):
        file_stream = BytesIO(b"unsupported content")
        with pytest.raises(FileValidationError):
            service.validate_file(file_stream, "test.xyz")

    def test_validate_file_too_large(self, service):
        large_content = b"x" * (101 * 1024 * 1024)
        file_stream = BytesIO(large_content)
        with pytest.raises(FileValidationError):
            service.validate_file(file_stream, "large.pdf")

    def test_count_pages_rejects_corrupt_pdf(self, service, tmp_path):
        corrupt = tmp_path / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7 garbage not a real pdf")
        with pytest.raises(FileValidationError, match="Corrupt or unreadable PDF"):
            service.count_pages(corrupt, DocumentType.PDF)

    def test_calculate_sha256(self, service, sample_pdf_bytes):
        file_stream = BytesIO(sample_pdf_bytes)
        sha256 = service.calculate_sha256(file_stream)
        assert len(sha256) == 64
        assert all(c in "0123456789abcdef" for c in sha256)

    @pytest.mark.asyncio
    async def test_ingest_file_pdf(self, service, sample_pdf_bytes, tmp_path):
        original_file = tmp_path / "original.pdf"
        original_file.write_bytes(sample_pdf_bytes)

        processed_file = tmp_path / "processed.pdf"
        processed_file.write_bytes(sample_pdf_bytes)

        with (
            patch.object(service, "detect_document_type", return_value=DocumentType.PDF),
            patch.object(service, "count_pages", return_value=1),
            patch.object(service, "extract_text", return_value=("Sample text", True)),
            patch.object(service, "create_searchable_pdf", return_value=processed_file),
            patch.object(service, "save_original", return_value=original_file),
            patch.object(service, "calculate_sha256", return_value="a" * 64),
        ):
            file_stream = BytesIO(sample_pdf_bytes)
            result = await service.ingest_file(
                file=file_stream,
                original_filename="test.pdf",
                packet_id="00000000-0000-0000-0000-000000000001",
                display_order=1,
            )
            assert result.document is not None
            assert result.document.original_filename == "test.pdf"
            assert result.document.document_type.value == "pdf"

    def test_detect_document_type_pdf(self, service, tmp_path):
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n%Test\n%%EOF")
        doc_type = service.detect_document_type("application/pdf", pdf_file)
        assert doc_type in ["pdf", "scanned_pdf"]

    def test_count_pages_image(self, service, tmp_path):
        image_file = tmp_path / "test.png"
        from PIL import Image

        Image.new("RGB", (100, 100)).save(image_file)
        count = service.count_pages(image_file, "image")
        assert count == 1

    def test_extract_text_image(self, service, tmp_path):
        image_file = tmp_path / "test.png"
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="white")
        img.save(image_file)
        text, searchable = service.extract_text(image_file, "image")
        assert isinstance(text, str)
        assert isinstance(searchable, bool)
