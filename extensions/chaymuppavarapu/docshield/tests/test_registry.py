from pathlib import Path

import pytest

from src.adapters.registry import parse_document


def test_unsupported_format_is_rejected(tmp_path: Path):
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"fake pdf")

    with pytest.raises(ValueError, match="Unsupported document format"):
        parse_document(path)


def test_missing_file_is_rejected(tmp_path: Path):
    path = tmp_path / "missing.docx"

    with pytest.raises(FileNotFoundError):
        parse_document(path)