"""
Proves rfi_patch.py fixes the two classes of bug found live:
1. Build 1's class - AI edit updates some Response fields but not all
   (see Build 1's README, Bugs 8-9).
2. Build 2's own bug 4 - the header table's Status cell is written once
   at initial upload and sits outside the Response chunk entirely, so
   it goes stale the moment the RFI is answered unless something
   explicitly re-patches it too.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from construction_data import fetch_open_rfi, fetch_rfi_response_event
from document_builder import build_rfi_document_html
from rfi_patch import patch_response_fields

RESPONSE_CHUNK_ID = "chunk_1"


def _answered_html_with_chunk_id() -> tuple[str, dict]:
    """A correctly-answered document, then tag the Response <p> with a
    data-chunk-id the way SuperDocs' server does after an edit lands."""
    rfi = fetch_open_rfi()
    event = fetch_rfi_response_event()
    answered = replace(
        rfi,
        status=event["status"],
        response=event["response"],
        responded_by=event["responded_by"],
        date_responded=event["date_responded"],
        cost_impact=event["cost_impact"],
        schedule_impact=event["schedule_impact"],
    )
    html = build_rfi_document_html(answered)
    tagged = html.replace(f"<p>{answered.response}</p>", f'<p data-chunk-id="{RESPONSE_CHUNK_ID}">{answered.response}</p>', 1)
    assert tagged != html, "test setup sanity check: could not tag the Response <p>"
    return tagged, event


def test_patch_response_fields_fixes_a_stale_header_status_cell():
    # Bug 4, caught live: the header table's Status cell is outside the
    # Response chunk, so it's never touched by the chat_async edit and
    # stays "Open" forever unless patch_response_fields fixes it too -
    # even when the Response block below it is already correct.
    html, event = _answered_html_with_chunk_id()
    stale_header_html = html.replace(
        "<td><strong>Status</strong></td><td>Answered</td>",
        "<td><strong>Status</strong></td><td>Open</td>",
        1,
    )
    assert stale_header_html != html, "test setup sanity check"

    patched = patch_response_fields(stale_header_html, event, RESPONSE_CHUNK_ID)

    assert "<td><strong>Status</strong></td><td>Answered</td>" in patched
    assert "<td><strong>Status</strong></td><td>Open</td>" not in patched


def test_patch_response_fields_preserves_attributes_on_the_header_status_cell():
    # Mirrors the precedent already proven for the Response chunk: if
    # the server ever decorates the header Status <td> with its own
    # attribute, only the value inside should change.
    html = (
        "<div><table>"
        '<tr><td><strong>Status</strong></td><td data-chunk-id="hdr1">Open</td></tr>'
        "</table><h2>Response</h2>"
        f'<p data-chunk-id="{RESPONSE_CHUNK_ID}">stale</p></div>'
    )
    event = fetch_rfi_response_event()

    patched = patch_response_fields(html, event, RESPONSE_CHUNK_ID)

    assert 'data-chunk-id="hdr1"' in patched
    assert f">{event['status']}</td>" in patched


def test_patch_response_fields_raises_loudly_when_header_status_cell_missing():
    html_without_header_status = (
        f'<div><table></table><h2>Response</h2><p data-chunk-id="{RESPONSE_CHUNK_ID}">x</p></div>'
    )
    event = fetch_rfi_response_event()

    with pytest.raises(RuntimeError, match="header table's Status cell"):
        patch_response_fields(html_without_header_status, event, RESPONSE_CHUNK_ID)


def test_patch_response_fields_forces_every_response_field_to_the_event_values():
    html, event = _answered_html_with_chunk_id()
    stale = html.replace(event["response"], "STALE RESPONSE TEXT", 1)

    patched = patch_response_fields(stale, event, RESPONSE_CHUNK_ID)

    assert event["response"] in patched
    assert event["responded_by"] in patched
    assert event["date_responded"] in patched
    assert event["cost_impact"] in patched
    assert event["schedule_impact"] in patched
    assert "STALE RESPONSE TEXT" not in patched


def test_patch_response_fields_never_touches_question_or_spec_fields():
    html, event = _answered_html_with_chunk_id()
    rfi = fetch_open_rfi()

    patched = patch_response_fields(html, event, RESPONSE_CHUNK_ID)

    assert rfi.spec_section in patched
    assert rfi.drawing_reference in patched
    assert rfi.question in patched


def test_patch_response_fields_tolerates_server_added_attributes_on_response_chunk():
    """
    Build 1's live testing found that SuperDocs adds server-side
    attributes (e.g. extra classes) to elements it returns after an
    edit. The chunk-id regex matches by data-chunk-id regardless of
    what other attributes ride along on the same tag.
    """
    event = fetch_rfi_response_event()
    html_with_server_attributes = (
        "<div><table>"
        "<tr><td><strong>Status</strong></td><td>Open</td></tr>"
        "</table><h2>Response</h2>"
        f'<p class="server-added" data-chunk-id="{RESPONSE_CHUNK_ID}">stale</p></div>'
    )

    patched = patch_response_fields(html_with_server_attributes, event, RESPONSE_CHUNK_ID)

    assert event["response"] in patched
    assert event["responded_by"] in patched
    assert f">{event['status']}</td>" in patched  # header cell also fixed


def test_patch_response_fields_raises_loudly_when_response_chunk_missing():
    html, event = _answered_html_with_chunk_id()
    html_without_chunk = html.replace(f'data-chunk-id="{RESPONSE_CHUNK_ID}"', "")

    with pytest.raises(RuntimeError, match="could not locate the Response block"):
        patch_response_fields(html_without_chunk, event, RESPONSE_CHUNK_ID)
