import pytest
from backend.core.retrieval.chunker import DocumentChunker, Chunk


def test_chunk_plain_text_returns_chunks():
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    text = "word " * 100  # 500 chars
    chunks = chunker.chunk(text, document_id="doc-1")
    assert len(chunks) >= 2
    for c in chunks:
        assert isinstance(c, Chunk)
        assert c.document_id == "doc-1"
        assert len(c.text) > 0


def test_chunk_assigns_sequential_indices():
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=0)
    text = "a " * 200
    chunks = chunker.chunk(text, document_id="doc-1")
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_short_text_produces_one_chunk():
    chunker = DocumentChunker(chunk_size=500, chunk_overlap=50)
    text = "Short document."
    chunks = chunker.chunk(text, document_id="doc-1")
    assert len(chunks) == 1
    assert chunks[0].text.strip() == "Short document."


def test_chunk_empty_text_returns_empty():
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.chunk("", document_id="doc-1")
    assert chunks == []


def test_chunk_preserves_page_number():
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.chunk("test content " * 30, document_id="doc-1", page_number=3)
    for c in chunks:
        assert c.page_number == 3


def test_chunk_metadata_contains_document_id():
    chunker = DocumentChunker(chunk_size=200, chunk_overlap=20)
    chunks = chunker.chunk("hello world " * 50, document_id="abc-123")
    for c in chunks:
        assert c.metadata["document_id"] == "abc-123"
