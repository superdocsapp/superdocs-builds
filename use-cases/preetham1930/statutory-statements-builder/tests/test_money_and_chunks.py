"""The recogniser, in both directions, and the chunk model it feeds."""

from __future__ import annotations

from decimal import Decimal

import pytest
from recorded import read_back_html
from statutory.chunks import ChunkMap, canonical, strip_chunk_ids
from statutory.money import format_money, money_tokens, money_tokens_in_html, parse_money


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("total 2,180.00 here", ["2,180.00"]),
        ("a loss of (45.00) this year", ["(45.00)"]),
        ("50,00,000 equity shares", ["50,00,000"]),
        ("INR 6,50,000 per month", ["6,50,000"]),
        ("earnings per share 8.14", ["8.14"]),
        ("42,000 sq ft", ["42,000"]),
        ("sums to 821.00 (703.00 + 87.00)", ["821.00", "703.00", "87.00"]),
    ],
)
def test_the_recogniser_finds_what_it_must(text: str, expected: list[str]) -> None:
    assert money_tokens(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "for the year ended 31 March 2026",
        "interest at 9.15% per annum",
        "CIN: U29253TG2016PLC112447",
        "Plot 42, IDA Nacharam, Hyderabad 500076",
        "a term of 5 years with a lock-in of 36 months",
        "100% of the equity share capital",
        "Companies (Indian Accounting Standards) Rules, 2015",
    ],
)
def test_the_recogniser_leaves_what_is_not_a_figure(text: str) -> None:
    assert money_tokens(text) == []


def test_brackets_are_matched_as_a_pair_or_not_at_all() -> None:
    """The Phase 3 silent-skip: an independent optional bracket matched "(703.00"."""
    assert "(703.00" not in money_tokens("sums to 821.00 (703.00 + 87.00)")
    assert money_tokens("(1,462.00)") == ["(1,462.00)"]


def test_format_and_parse_round_trip() -> None:
    for value in ("0.00", "-45.00", "4857.00", "-1691.00", "12.50"):
        assert parse_money(format_money(Decimal(value))) == Decimal(value)
    assert format_money(Decimal("-0.00")) == "0.00", "a nil balance is never '-0.00'"


def test_markup_never_contributes_a_figure() -> None:
    fragment = (
        '<td data-chunk-id="1f2adf88-8741-40b3-a5c7-f443314369ab" '
        'style="border:1px solid #1f3864;padding:6px">40.00</td>'
    )
    assert money_tokens_in_html(fragment) == ["40.00"]


def test_canonical_ignores_whitespace_attribute_order_and_the_chunk_id() -> None:
    left = '<p data-chunk-id="abc"  style="color:red" class="x">a   b</p>'
    right = '<p class="x" style="color:red">a b</p>'
    assert canonical(left) == canonical(right)


def test_canonical_treats_an_entity_and_its_character_as_the_same_content() -> None:
    """Measured on the first live upload: we sent `&middot;` and got back `·`."""
    assert canonical("<p>a &middot; b</p>") == canonical("<p>a · b</p>")
    assert canonical("<h3>Note 4 &mdash; Leases</h3>") == canonical("<h3>Note 4 — Leases</h3>")


def test_canonical_treats_a_void_element_the_same_either_way() -> None:
    """Measured on the first live upload: we sent `<br>` and got back `<br/>`."""
    assert canonical("<p>a<br>b</p>") == canonical("<p>a<br/>b</p>")


def test_canonical_never_ignores_a_digit() -> None:
    assert canonical("<p>724</p>") != canonical("<p>750</p>")
    assert canonical('<td style="a">1.00</td>') != canonical('<td style="a">1.01</td>')


def test_a_recorded_document_parses_into_the_chunks_the_product_addressed() -> None:
    chunks = ChunkMap(read_back_html("read0-baseline"))
    assert len(chunks) == 18
    assert all(chunk.chunk_id for chunk in chunks.chunks)
    assert chunks.chunks[0].tag == "h1"
    assert "724" in chunks.by_id["8ec79daa-5de5-4973-84a5-1d1139da29be"].html


def test_headings_are_read_back_out_of_the_document(rolled) -> None:
    headings = ChunkMap(rolled.document.html("target")).headings()
    assert len(headings) == 27
    assert headings[4].startswith("Note 4")
    assert "Leases" in headings[4]


def test_strip_chunk_ids_is_exact() -> None:
    assert strip_chunk_ids('<p data-chunk-id="x">a</p>') == "<p>a</p>"
