"""
Proves document_builder.py's "must never" guarantees, and directly
targets the task's own stated bar for this build: "Reviewer supplies
one fictional RFI payload with a spec section and a drawing reference,
and the generated document carries both references correctly into the
formal RFI format."
"""

from construction_data import fetch_open_rfi, fetch_rfi_response_event
from document_builder import build_rfi_document_html


def test_spec_section_and_drawing_reference_carry_through_verbatim():
    """THE strong-bar test: both fields must appear byte-exact in the
    generated document."""
    rfi = fetch_open_rfi()
    html = build_rfi_document_html(rfi)

    assert rfi.spec_section in html
    assert rfi.drawing_reference in html


def test_every_header_field_appears():
    rfi = fetch_open_rfi()
    html = build_rfi_document_html(rfi)

    for value in [
        rfi.rfi_number,
        rfi.project_name,
        rfi.subject,
        rfi.submitted_by,
        rfi.submitted_to,
        rfi.date_submitted,
        rfi.date_required,
    ]:
        assert value in html


def test_question_text_appears_verbatim():
    rfi = fetch_open_rfi()
    html = build_rfi_document_html(rfi)
    assert rfi.question in html


def test_open_rfi_shows_awaiting_response_not_a_fabricated_answer():
    """Must never invent a response - an unanswered RFI must say so
    plainly, never show blank/fake response fields."""
    rfi = fetch_open_rfi()
    html = build_rfi_document_html(rfi)
    assert "Awaiting response" in html
    assert "Responded By" not in html


def test_answered_rfi_shows_response_block():
    from dataclasses import replace

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

    assert event["response"] in html
    assert event["responded_by"] in html
    assert event["cost_impact"] in html
    assert event["schedule_impact"] in html
    assert "Awaiting response" not in html
