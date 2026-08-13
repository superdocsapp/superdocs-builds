from src.source import SourceDocument
from src.source_validator import validate_source


def test_identical_source_is_detected(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_bytes(b"original document")

    source = SourceDocument.load(path)

    result = validate_source(
        source,
        b"original document",
    )

    assert result.identical is True
    assert result.changed is False
    assert (
        result.original_sha256
        == result.edited_sha256
    )


def test_changed_source_is_detected(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_bytes(b"original document")

    source = SourceDocument.load(path)

    result = validate_source(
        source,
        b"edited document",
    )

    assert result.identical is False
    assert result.changed is True
    assert (
        result.original_sha256
        != result.edited_sha256
    )


def test_empty_edited_source_is_still_detected_as_changed(
    tmp_path,
):
    path = tmp_path / "resume.txt"
    path.write_bytes(b"original document")

    source = SourceDocument.load(path)

    result = validate_source(
        source,
        b"",
    )

    assert result.identical is False
    assert result.changed is True
