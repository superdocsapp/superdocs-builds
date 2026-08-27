"""Tests for header/footer stamping and controlled PDF export."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from build_a.client import SuperDocsClient
from build_a.headers import ControlledExporter, HeaderFooterStamper

TEST_API_KEY = "sk_test_key"


@pytest.mark.asyncio
@respx.mock
async def test_build_combined_instruction() -> None:
    """Combined instruction includes both header and footer."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        stamper = HeaderFooterStamper(client)
        instruction = stamper.build_combined_instruction("0042", "2025-01-15")
        assert "Revision 0042" in instruction
        assert "2025-01-15" in instruction
        assert "page numbers" in instruction.lower()


@pytest.mark.asyncio
@respx.mock
async def test_build_header_instruction() -> None:
    """Header instruction references revision number and date."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        stamper = HeaderFooterStamper(client)
        instruction = stamper.build_header_instruction("0099", "2025-06-01")
        assert "Revision 0099" in instruction
        assert "2025-06-01" in instruction


@pytest.mark.asyncio
@respx.mock
async def test_stamp_sends_single_chat_turn() -> None:
    """Stamp sends exactly one chat instruction for both header and footer."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "response": "Headers and footers updated",
                "session_id": "test-session",
                "document_changes": {},
            })
        )
        stamper = HeaderFooterStamper(client)
        result = await stamper.stamp("test-session", "0042", "2025-01-15")
        assert result.ops_used == 1
        assert "Revision 0042" in result.header_text


@pytest.mark.asyncio
@respx.mock
async def test_stamp_records_operation() -> None:
    """Stamp increments the client's operation tracker."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/chat").mock(
            return_value=httpx.Response(200, json={
                "response": "Done",
                "session_id": "test-session",
                "document_changes": {},
            })
        )
        stamper = HeaderFooterStamper(client)
        await stamper.stamp("test-session", "0042", "2025-01-15")
        assert client.tracker.total_ops == 1


@pytest.mark.asyncio
@respx.mock
async def test_export_pdf_saves_to_disk(tmp_path) -> None:
    """Export downloads PDF bytes and writes to the specified path."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/documents/export").mock(
            return_value=httpx.Response(200, json={
                "download_url": "https://cdn.example.com/test.pdf",
            })
        )
        respx.get("https://cdn.example.com/test.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 fake")
        )
        exporter = ControlledExporter(client)
        result = await exporter.export_pdf(
            "test-session",
            tmp_path / "output.pdf",
        )
        assert result.pdf_path.exists()
        assert result.pdf_path.read_bytes() == b"%PDF-1.4 fake"
        assert client.tracker.total_ops == 0  # export = 0 ops


@pytest.mark.asyncio
@respx.mock
async def test_export_falls_back_to_presigned_url(tmp_path) -> None:
    """When direct export fails, falls back to pre-signed download URL."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        # Direct export fails
        respx.post("https://api.superdocs.app/v1/documents/export").mock(
            return_value=httpx.Response(500, json={"error": "Internal error"})
        )
        # Pre-signed URL succeeds
        respx.post("https://api.superdocs.app/v1/downloads").mock(
            return_value=httpx.Response(200, json={
                "download_url": "https://cdn.example.com/fallback.pdf",
                "expires_at": "2025-01-02T00:00:00Z",
                "expires_in_seconds": 86400,
                "curl_example": "curl -o fallback.pdf https://cdn.example.com/fallback.pdf",
                "filename": "fallback.pdf",
                "format": "pdf",
            })
        )
        respx.get("https://cdn.example.com/fallback.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4 fallback")
        )
        exporter = ControlledExporter(client)
        result = await exporter.export_pdf(
            "test-session",
            tmp_path / "fallback.pdf",
        )
        assert result.pdf_path.exists()
        assert result.pdf_path.read_bytes() == b"%PDF-1.4 fallback"


@pytest.mark.asyncio
@respx.mock
async def test_export_records_zero_ops(tmp_path: Path) -> None:
    """Export is free — tracker should not increase for export ops."""
    async with SuperDocsClient(api_key=TEST_API_KEY) as client:
        respx.post("https://api.superdocs.app/v1/documents/export").mock(
            return_value=httpx.Response(200, json={
                "download_url": "https://cdn.example.com/doc.pdf",
            })
        )
        respx.get("https://cdn.example.com/doc.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF")
        )
        initial_ops = client.tracker.total_ops
        exporter = ControlledExporter(client)
        await exporter.export_pdf("test-session", tmp_path / "test.pdf")
        # export() = 0 ops, download = 0 ops
        assert client.tracker.total_ops == initial_ops
