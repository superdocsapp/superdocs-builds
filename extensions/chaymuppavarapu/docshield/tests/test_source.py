from pathlib import Path

import pytest

from src.source import SourceDocument


def test_source_document_loads_original_bytes(tmp_path: Path):
    path = tmp_path / "resume.html"
    original = b"<html><body>Hello</body></html>"
    path.write_bytes(original)

    source = SourceDocument.load(path)

    assert source.path == path
    assert source.filename == "resume.html"
    assert source.extension == ".html"
    assert source.data == original
    assert source.verify(original) is True


def test_source_document_detects_modified_bytes(tmp_path: Path):
    path = tmp_path / "resume.html"
    original = b"<html><body>Hello</body></html>"
    path.write_bytes(original)

    source = SourceDocument.load(path)

    modified = b"<html><body>Changed</body></html>"

    assert source.verify(modified) is False


def test_source_document_rejects_missing_file(tmp_path: Path):
    path = tmp_path / "missing.html"

    with pytest.raises(FileNotFoundError):
        SourceDocument.load(path)


def test_source_document_rejects_empty_file(tmp_path: Path):
    path = tmp_path / "empty.html"
    path.write_bytes(b"")

    with pytest.raises(ValueError, match="empty"):
        SourceDocument.load(path)


def test_source_document_rejects_directory(tmp_path: Path):
    path = tmp_path / "documents"
    path.mkdir()

    with pytest.raises(ValueError, match="Not a file"):
        SourceDocument.load(path)