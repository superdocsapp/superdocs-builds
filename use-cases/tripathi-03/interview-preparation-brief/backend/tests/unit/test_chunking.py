from app.services.rag.chunking import chunk_text


def test_chunk_text_respects_size_and_overlap():
    text = "a" * 1000
    chunks = chunk_text(text, chunk_size=300, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 300 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("   ") == []
