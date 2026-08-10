"""Ledger rows that are claims about the published surface, asserted against it.

Not every behaviour needs a live call to be defended. A good part of the ledger is claims
about what SuperDocs *publishes* -- an enum, a required field, a pattern, a tool argument.
Those are checked directly against the pinned spec and the pinned tool surface, and they
fail the moment either moves.

The value is that these rows stop being prose. When the spec changes `session_id`'s
pattern or drops `include_html` from a tool, a test goes red with the row number on it
instead of an integrator finding out in production.

Everything here runs offline, in milliseconds, with no key and no mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdmock.cassette import load_all
from sdmock.spec import load as load_spec

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.rest


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def schemas(spec):
    return spec.schemas


@pytest.fixture(scope="module")
def cassettes():
    return load_all(ROOT / "cassettes")


@pytest.fixture(scope="module")
def pinned_tools() -> dict[str, dict]:
    raw = json.loads((ROOT / "spec" / "mcp-tools.json").read_text(encoding="utf-8"))
    return {tool["name"]: tool for tool in raw["tools"]}


# ------------------------------------------------------------------ the spec's claims


def test_auth_scheme_is_bearer(spec):
    """B-001."""
    schemes = spec.raw["components"]["securitySchemes"]
    assert schemes["HTTPBearer"] == {"type": "http", "scheme": "bearer"}


def test_session_id_pattern_and_length(schemas):
    """B-009. Clients build session ids from user data; the pattern is load-bearing."""
    field = schemas["UniversalChatRequest"]["properties"]["session_id"]
    assert field["pattern"] == r"^[a-zA-Z0-9_\-\.]+$"
    assert field["maxLength"] == 256


def test_document_html_is_a_wholesale_replacement(schemas):
    """B-011. Re-sending it replaces the server's copy; it is not a delta."""
    described = schemas["UniversalChatRequest"]["properties"]["document_html"]["description"]
    assert "replace the document wholesale" in described
    assert "verbatim load" in described


def test_chat_response_requires_response_and_session_id(schemas):
    """B-014."""
    assert set(schemas["ChatResponse"]["required"]) == {"response", "session_id"}


def test_document_changes_is_only_present_when_something_changed(schemas):
    """B-015."""
    described = schemas["ChatResponse"]["properties"]["document_changes"]["description"]
    assert "Present only when the document was changed" in described


def test_quota_exhausted_still_completes_the_current_request(schemas):
    """B-019. The difference between 'this failed' and 'the next one will'."""
    described = schemas["UsageInfo"]["properties"]["quota_exhausted"]["description"]
    assert "current request still completes" in described


def test_hint_is_advisory_and_usually_absent(schemas):
    """B-021. A client must not require it."""
    described = schemas["ChatResponse"]["properties"]["hint"]["description"]
    assert "additive" in described and "absent on most responses" in described
    assert "prefer_chat_async_for_large_generations" in described


def test_model_tier_and_thinking_depth_enumerations(schemas):
    """B-022. Sending an unlisted tier is a client bug worth catching early."""
    properties = schemas["UniversalChatRequest"]["properties"]
    tiers = properties["model_tier"]["description"]
    depths = properties["thinking_depth"]["description"]
    for tier in ("core", "turbo", "pro", "max"):
        assert f"'{tier}'" in tiers
    for depth in ("fast", "balanced", "deep"):
        assert f"'{depth}'" in depths


def test_job_types(schemas):
    """B-028."""
    described = schemas["JobResponse"]["properties"]["job_type"]["description"]
    assert "chat" in described and "attachment_processing" in described


def test_continue_semantics_keep_completed_work(schemas):
    """B-037. `continue: false` stops; it does not roll back."""
    described = schemas["ContinueRequest"]["properties"]["continue"]["description"]
    assert "fresh budget" in described
    assert "work so far is kept" in described


def test_pending_change_carries_its_document(schemas):
    """B-047. Multi-document review lists are grouped by this."""
    properties = schemas["PendingChange"]["properties"]
    assert "document_id" in properties
    assert set(schemas["PendingChange"]["required"]) == {"change_id", "operation"}


def test_one_operation_covers_twenty_five_sections(schemas):
    """B-088. The unit of billing, and the reason ops_charged can exceed one."""
    described = schemas["UsageInfo"]["properties"]["ops_charged"]["description"]
    assert "one per 25 sections" in described


def test_upload_routes_publish_no_response_shape(spec):
    """B-103, and F-004's remaining substance."""
    for template in ("/v1/documents/upload", "/v1/documents/upload-base64"):
        schema = (spec.operation("post", template)["responses"]["200"]
                  .get("content", {}).get("application/json", {}).get("schema"))
        assert schema == {}, f"{template} now documents a response -- close F-004"
    process = spec.response_schema("post", "/v1/uploads/{upload_id}/process", 200)
    assert process is not None and "$ref" in process


# ------------------------------------------------------------------ the tool surface


@pytest.mark.mcp
def test_token_light_tools_take_include_html(pinned_tools):
    """B-100. The default is compact; the opt-in has to exist to be opted into."""
    for name in ("list_documents", "list_session_documents", "get_document_detail"):
        properties = (pinned_tools[name].get("inputSchema") or {}).get("properties") or {}
        assert "include_html" in properties, f"{name} lost its include_html argument"


@pytest.mark.mcp
def test_document_detail_offers_a_free_structure_outline(pinned_tools):
    """B-102. The cheap way to verify an edit landed without paying for an export."""
    described = pinned_tools["get_document_detail"].get("description", "")
    assert "structure" in described
    assert "never export just to check" in described


@pytest.mark.mcp
def test_process_uploaded_document_is_compact_by_default(pinned_tools):
    """B-099."""
    described = pinned_tools["process_uploaded_document"].get("description", "")
    assert "compact result by default" in described
    assert "return_html=true" in described


@pytest.mark.mcp
def test_the_tool_surface_is_pinned_because_it_ships_live(pinned_tools):
    """B-097, asserted as the reason this pin exists at all.

    Tools are served from the backend, so nothing local pins them unless we do. The
    guard is that the pin exists, is non-trivial, and has a checker wired to it.
    """
    assert len(pinned_tools) == 38
    assert (ROOT / "spec" / "mcp-tools.json").exists()
    checker = (ROOT / "scripts" / "pin_mcp_surface.py").read_text(encoding="utf-8")
    assert "--check" in checker, "the pin has no drift checker"


# ------------------------------------------------------------------ the recordings


def test_every_recorded_error_carries_a_detail_field(cassettes):
    """B-063. Clients branch on `detail`; a bare body would break them all."""
    offenders: list[str] = []
    for name, cassette in cassettes.items():
        for interaction in cassette.interactions:
            response = interaction.response
            if response.status < 400 or response.json_body is None:
                continue
            if not isinstance(response.json_body, dict) or "detail" not in response.json_body:
                offenders.append(f"{name}/{interaction.id} -> {response.status}")
    assert not offenders, "error responses with no `detail`: " + ", ".join(offenders)


def test_the_review_loop_can_run_more_than_one_round(cassettes):
    """B-048. Denying with feedback reopens the review -- observed, not assumed.

    A polling loop written for a single round hangs here, which is why it is worth
    having a fixture that proves the second round is real.
    """
    cassette = cassettes["proposed-change-batch"]
    pauses = [
        interaction for interaction in cassette.interactions
        if interaction.request.method == "GET"
        and (interaction.response.json_body or {}).get("status") == "awaiting_approval"
    ]
    assert len(pauses) >= 2, (
        "only one review round is recorded; the multi-round loop is unproven"
    )
    decisions = [
        interaction for interaction in cassette.interactions
        if interaction.request.path.endswith("/approve")
        and interaction.response.status == 200
    ]
    assert len(decisions) >= 2, "only one approve call recorded"


def test_a_review_pause_omits_awaiting_kind_entirely(cassettes):
    """B-105. Absence is the signal, and code that tests for a *value* misses it."""
    cassette = cassettes["proposed-change-batch"]
    for interaction in cassette.interactions:
        body = interaction.response.json_body or {}
        if body.get("status") != "awaiting_approval":
            continue
        metadata = body.get("metadata") or {}
        assert "awaiting_kind" not in metadata, (
            "a review pause now carries awaiting_kind -- the docs' 'otherwise' branch "
            "has become explicit, which is an improvement worth noting in findings.md"
        )
        assert metadata.get("pending_changes"), "a review pause with nothing to review"


def test_batch_decisions_default_to_the_top_level_flag(cassettes):
    """B-043. The recorded batch relies on it, which is what makes it testable."""
    cassette = cassettes["proposed-change-batch"]
    batched = [
        interaction for interaction in cassette.interactions
        if interaction.request.path.endswith("/approve")
        and isinstance(interaction.request.json_body, dict)
        and "changes" in (interaction.request.json_body or {})
    ]
    assert batched, "no batch approval recorded"
    accepted = [b for b in batched if b.response.status == 200]
    rejected = [b for b in batched if b.response.status == 422]
    assert accepted and rejected, (
        "the cassette should carry both a valid batch and the one missing top-level "
        "`approved`, since the difference is the whole lesson"
    )
    for interaction in accepted:
        assert "approved" in interaction.request.json_body


def test_sse_authenticates_by_query_parameter(cassettes):
    """B-004. EventSource cannot set headers, so the key rides the URL -- scrubbed."""
    cassette = cassettes["proposed-change-batch"]
    streams = [i for i in cassette.interactions if i.response.sse]
    assert streams, "no stream recorded"
    for interaction in streams:
        assert "api_key" in interaction.request.query
        assert interaction.request.query["api_key"] == "[REDACTED]", (
            "a live api_key survived into a recorded stream URL"
        )


def test_client_chosen_session_ids_are_what_was_recorded(cassettes):
    """B-008. No create-session call exists; the ids below were simply chosen."""
    cassette = cassettes["proposed-change-batch"]
    starts = [
        i for i in cassette.interactions
        if i.request.path == "/v1/chat/async" and isinstance(i.request.json_body, dict)
    ]
    assert starts, "no chat/async recorded"
    assert starts[0].request.json_body["session_id"] == "sdmock-review-001"
    assert not any(
        i.request.path.endswith("/sessions") and i.request.method == "POST"
        for i in cassette.interactions
    ), "a create-session call appeared; the session model has changed"


def test_a_follow_up_turn_need_not_resend_the_document(cassettes):
    """B-010. The server holds the document; only the first turn carries HTML."""
    cassette = cassettes["large-multi-section-edit"]
    starts = [i for i in cassette.interactions if i.request.path == "/v1/chat/async"]
    assert starts
    assert "document_html" in (starts[0].request.json_body or {}), (
        "the loading turn should carry the document"
    )
