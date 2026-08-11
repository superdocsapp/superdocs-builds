import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.app.services.ingestion import IngestionService, chunk_segments
from backend.app.services.parsing import ExtractedSegment
from backend.app.exceptions import DuplicateFileError, FileIngestionError
from backend.app.models import Document

def test_chunk_segments_combining():
    segments = [
        ExtractedSegment(content="Intro sentence 1.", page_number=None, section="Overview"),
        ExtractedSegment(content="Intro sentence 2.", page_number=None, section="Overview"),
        ExtractedSegment(content="Details on page 1.", page_number=1, section="Details"),
    ]
    # Group segments sharing same metadata together
    chunks = chunk_segments(segments, chunk_size=500, chunk_overlap=100)
    assert len(chunks) == 2
    assert chunks[0].content == "Intro sentence 1.\nIntro sentence 2."
    assert chunks[0].section == "Overview"
    assert chunks[0].page_number is None
    
    assert chunks[1].content == "Details on page 1."
    assert chunks[1].section == "Details"
    assert chunks[1].page_number == 1

def test_chunk_segments_splitting():
    large_text = "X" * 1800
    segments = [
        ExtractedSegment(content=large_text, page_number=3, section="Scale"),
    ]
    chunks = chunk_segments(segments, chunk_size=1000, chunk_overlap=200)
    assert len(chunks) == 2
    assert chunks[0].content == "X" * 1000
    assert chunks[0].page_number == 3
    assert chunks[0].chunk_index == 0
    
    # 1800 length chunked with 1000 size and 200 overlap:
    # First chunk: 0 to 1000
    # Second chunk: starts at 1000 - 200 = 800, goes to 1800 (1000 chars)
    assert len(chunks[1].content) == 1000
    assert chunks[1].chunk_index == 1
    assert chunks[1].page_number == 3

@pytest.mark.asyncio
async def test_ingest_duplicate_handling(mock_db_session):
    existing_doc = Document(filename="original.txt", hash_sha256="somehash")
    
    # Mocking select(Document) result
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = existing_doc
    mock_db_session.execute.return_value = mock_res
    
    service = IngestionService(mock_db_session)
    with pytest.raises(DuplicateFileError) as exc_info:
        await service.ingest_document("upload.txt", b"duplicate text content")
    assert "Duplicate document detected" in str(exc_info.value)

@pytest.mark.asyncio
async def test_ingest_oversized_validation(mock_db_session):
    service = IngestionService(mock_db_session)
    oversized_data = b"B" * (11 * 1024 * 1024)  # 11MB (Limit is 10MB)
    with pytest.raises(FileIngestionError) as exc_info:
        await service.ingest_document("huge.txt", oversized_data)
    assert "exceeds maximum limit of 10MB" in str(exc_info.value)
