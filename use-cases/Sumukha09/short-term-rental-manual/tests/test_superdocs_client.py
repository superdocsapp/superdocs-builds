import base64
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from mock_data import ASSETS_DIR, load_mock_catalog
from superdocs_client import RecordingMcpInvoker, SuperDocsClient
from workflow import build_preview, export_manual_after_approved_edit


MCP_RESPONSES = {
    "upload_document_base64": {"document_id": "doc-123", "session_id": "sess-456", "version": 3},
    "chat_async": {
        "change_id": "chg-789",
        "status": "awaiting_approval",
        "proposed_change": '{"summary": "Quiet hours now end at 8 AM."}',
    },
    "approve_change": {"change_id": "chg-789", "status": "completed"},
    "export_document": {"document_id": "doc-123", "format": "pdf", "url": "https://superdocs.test/doc-123.pdf"},
}


def _run_live_flow(property_id="green", language="en", responses=None):
    invoker = RecordingMcpInvoker(responses or MCP_RESPONSES)
    result = export_manual_after_approved_edit(
        SuperDocsClient(invoker), load_mock_catalog(), property_id, language
    )
    return invoker, result


def test_live_flow_calls_mcp_tools_in_exact_order():
    invoker, _ = _run_live_flow()
    assert [tool for tool, _ in invoker.calls] == [
        "upload_document_base64",
        "chat_async",
        "approve_change",
        "export_document",
    ]


def test_uploaded_payload_decodes_to_html_with_expected_data_uris():
    invoker, result = _run_live_flow()
    upload_tool, upload_args = invoker.calls[0]
    assert upload_tool == "upload_document_base64"
    assert upload_args["mime_type"] == "text/html"
    assert upload_args["filename"] == "green-guest-manual-en.html"
    html = base64.b64decode(upload_args["content_base64"]).decode("utf-8")
    assert html.startswith("<!doctype html>")
    # 5 photos + 1 map + 1 cover reuse of photos[0] = 7 data URIs. bedroom_1.jpg is
    # PNG-encoded on disk and image_as_data_uri sniffs mime from bytes, not suffix.
    assert html.count("data:image/jpeg;base64,") == 5
    assert html.count("data:image/png;base64,") == 2
    assert result["document_id"] == "doc-123"
    assert result["session_id"] == "sess-456"


def test_edit_targets_uploaded_session_and_approval_is_explicit():
    invoker, result = _run_live_flow()
    _, chat_args = invoker.calls[1]
    _, approve_args = invoker.calls[2]
    _, export_args = invoker.calls[3]
    assert chat_args["session_id"] == "sess-456"
    assert chat_args["message"]
    assert approve_args == {"session_id": "sess-456", "change_id": "chg-789"}
    assert result["status_before_approval"] == "awaiting_approval"
    assert export_args == {"document_id": "doc-123", "format": "pdf", "session_id": "sess-456"}


def test_flow_refuses_to_approve_when_edit_is_not_awaiting_approval():
    responses = dict(MCP_RESPONSES)
    responses["chat_async"] = {"change_id": "chg-789", "status": "completed", "proposed_change": "{}"}
    invoker = RecordingMcpInvoker(responses)
    with pytest.raises(RuntimeError, match="awaiting_approval"):
        export_manual_after_approved_edit(
            SuperDocsClient(invoker), load_mock_catalog(), "green"
        )
    assert [tool for tool, _ in invoker.calls] == ["upload_document_base64", "chat_async"]


def test_flow_fails_clearly_when_upload_has_no_session():
    responses = dict(MCP_RESPONSES)
    responses["upload_document_base64"] = {"document_id": "doc-123"}
    with pytest.raises(RuntimeError, match="session_id"):
        _run_live_flow(responses=responses)


def test_blue_residency_generates_every_artifact_with_embedded_map():
    catalog = load_mock_catalog()
    artifacts = build_preview(catalog, "blue")
    assert set(artifacts) == {"manual.html", "listing.txt", "welcome_card.html"}
    assert artifacts["manual.html"].count("data:image/png;base64,") == 2  # map + PNG-encoded living_room
    assert artifacts["manual.html"].count("data:image/jpeg;base64,") == 2  # cover + exterior photo
    assert "BlueVillaNet" in artifacts["welcome_card.html"]
    assert "Blue Residency" in artifacts["listing.txt"]


def test_missing_map_asset_fails_with_a_clear_file_error():
    catalog = load_mock_catalog()
    catalog.get_property("blue").map_diagram.path = ASSETS_DIR / "blue_residency" / "missing_map.png"
    with pytest.raises(FileNotFoundError, match="missing_map"):
        build_preview(catalog, "blue")
