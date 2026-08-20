from io import BytesIO

import docx

from battlecard.template import build_filled_template_bytes


def test_deterministic_fields_are_filled_in_with_no_ai_call_needed():
    """The title and three given fields are plain text substitution -- this
    test proves that without touching the network, which is the whole point
    of doing it this way."""
    raw = build_filled_template_bytes(
        competitor_name="Zephyr Analytics",
        likely_pitch="Fastest setup, no engineering needed.",
        where_we_win="Our reports stay accurate automatically.",
        where_we_dont="Their onboarding really is faster.",
    )
    document = docx.Document(BytesIO(raw))
    all_text = "\n".join(p.text for p in document.paragraphs)

    assert "Zephyr Analytics — Battlecard" in all_text
    assert "Fastest setup, no engineering needed." in all_text
    assert "Our reports stay accurate automatically." in all_text
    assert "Their onboarding really is faster." in all_text
    assert "[COMPETITOR NAME]" not in all_text


def test_talk_track_is_left_as_a_placeholder_for_the_ai():
    raw = build_filled_template_bytes(
        competitor_name="Zephyr Analytics",
        likely_pitch="x", where_we_win="y", where_we_dont="z",
    )
    document = docx.Document(BytesIO(raw))
    all_text = "\n".join(p.text for p in document.paragraphs)
    assert "PLACEHOLDER" in all_text
    assert "Talk Track" in all_text


def test_two_competitors_produce_different_filled_templates():
    zephyr = build_filled_template_bytes("Zephyr Analytics", "pitch A", "win A", "dont A")
    brightfield = build_filled_template_bytes("Brightfield", "pitch B", "win B", "dont B")
    assert zephyr != brightfield
