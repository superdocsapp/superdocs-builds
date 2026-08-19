from __future__ import annotations

from app.util import (
    content_type_for_export_format,
    guess_content_type,
    is_supported_upload_extension,
    sanitize_session_id,
)


def test_sanitize_session_id_strips_slashes_and_spaces():
    raw = "incoming/My Contract (Final) v2.docx"
    cleaned = sanitize_session_id(raw)
    assert " " not in cleaned
    assert "/" not in cleaned
    assert "(" not in cleaned and ")" not in cleaned
    # Only the documented safe charset survives.
    assert all(c.isalnum() or c in "_.-" for c in cleaned)


def test_sanitize_session_id_is_deterministic():
    raw = "incoming/contract.txt"
    assert sanitize_session_id(raw) == sanitize_session_id(raw)


def test_sanitize_session_id_never_empty_and_within_length_cap():
    assert sanitize_session_id("") != ""
    assert len(sanitize_session_id("x" * 5000)) <= 200


def test_supported_upload_extensions_match_documented_set():
    assert is_supported_upload_extension("contract.docx")
    assert is_supported_upload_extension("notes.TXT")  # case-insensitive
    assert is_supported_upload_extension("report.pdf")
    assert not is_supported_upload_extension("archive.zip")
    assert not is_supported_upload_extension("image.png")


def test_content_type_for_export_format_has_sane_defaults():
    assert content_type_for_export_format("pdf") == "application/pdf"
    assert content_type_for_export_format("unknown-format") == "application/octet-stream"


def test_guess_content_type_falls_back_to_octet_stream():
    assert guess_content_type("file.docx").startswith(
        "application/"
    )
    assert guess_content_type("no-extension-at-all") == "application/octet-stream"
