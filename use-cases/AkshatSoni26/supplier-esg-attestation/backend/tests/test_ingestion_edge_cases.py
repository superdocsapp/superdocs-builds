"""Edge-case tests for IngestionService: corrupt PDF, empty file, unsupported format."""
import pytest
from app.services.ingestion_service import IngestionService


@pytest.fixture
def svc() -> IngestionService:
    return IngestionService()


class TestExtractTextFromStream:
    """Unit tests for IngestionService.extract_text_from_stream() edge cases."""

    def test_empty_txt_file_returns_empty_string(self, svc: IngestionService) -> None:
        """An empty TXT upload should not crash; it should return an empty string."""
        result = svc.extract_text_from_stream("response.txt", b"")
        assert result == ""

    def test_corrupt_pdf_gracefully_falls_back(self, svc: IngestionService) -> None:
        """A file with a .pdf extension but corrupt bytes must not raise; falls back to raw decode."""
        corrupt_bytes = b"NOT A REAL PDF \x00\x01\x02\x03"
        result = svc.extract_text_from_stream("corrupt_response.pdf", corrupt_bytes)
        # Must return something (the raw decode), not raise
        assert isinstance(result, str)

    def test_corrupt_docx_gracefully_falls_back(self, svc: IngestionService) -> None:
        """A file with a .docx extension but corrupt bytes must not raise; falls back to raw decode."""
        corrupt_bytes = b"PK\x03\x04THIS IS NOT A REAL DOCX"
        result = svc.extract_text_from_stream("broken.docx", corrupt_bytes)
        assert isinstance(result, str)

    def test_valid_txt_extracts_text(self, svc: IngestionService) -> None:
        """Plain UTF-8 text should be returned as-is."""
        content = b"Scope 1 emissions: 1200 mt CO2e\nScope 2 not tracked."
        result = svc.extract_text_from_stream("response.txt", content)
        assert "Scope 1 emissions" in result
        assert "Scope 2 not tracked" in result

    def test_json_file_extracts_as_text(self, svc: IngestionService) -> None:
        """A JSON file should be read as raw text (not parsed)."""
        content = b'{"scope_1": 500, "scope_2": null}'
        result = svc.extract_text_from_stream("data.json", content)
        assert "scope_1" in result

    def test_markdown_file_extracts_as_text(self, svc: IngestionService) -> None:
        """A markdown file should return raw text content."""
        content = b"# ESG Response\n\nWe have ISO 14001 certified EMS."
        result = svc.extract_text_from_stream("response.md", content)
        assert "ISO 14001" in result

    def test_unknown_extension_falls_back_to_text_decode(self, svc: IngestionService) -> None:
        """An unsupported extension (e.g. .xml) falls back to raw UTF-8 decode."""
        content = b"<root><scope>1200 mt CO2e</scope></root>"
        result = svc.extract_text_from_stream("data.xml", content)
        assert isinstance(result, str)
        assert "1200 mt CO2e" in result

    def test_empty_pdf_bytes_does_not_crash(self, svc: IngestionService) -> None:
        """Zero-byte file with .pdf extension must not raise an exception."""
        result = svc.extract_text_from_stream("empty.pdf", b"")
        assert isinstance(result, str)

    def test_empty_docx_bytes_does_not_crash(self, svc: IngestionService) -> None:
        """Zero-byte file with .docx extension must not raise an exception."""
        result = svc.extract_text_from_stream("empty.docx", b"")
        assert isinstance(result, str)
