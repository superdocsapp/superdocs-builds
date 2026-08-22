from src.doc_index import parse_markdown_chunks, find_doc_references


SAMPLE_README = """
# My Library

## Installation

Run `pip install mylib`.

## Usage

Call `compute_total(items)` to get the sum of all item prices in a cart.

## API Reference

### greet

The `greet` function returns a friendly greeting string for the given name.
"""


def test_finds_the_chunk_documenting_a_named_function():
    chunks = parse_markdown_chunks(SAMPLE_README)
    hits = find_doc_references(chunks, "compute_total")
    assert len(hits) == 1
    assert "compute_total" in hits[0].text


def test_returns_empty_for_a_function_never_mentioned():
    chunks = parse_markdown_chunks(SAMPLE_README)
    hits = find_doc_references(chunks, "totally_unrelated_function")
    assert hits == []


def test_word_boundary_prevents_partial_name_false_positives():
    """'get' must not match inside 'target' or 'budget' -- a naive substring search would false-positive
    constantly on short function names."""
    chunks = parse_markdown_chunks("This section discusses your budget and target audience.")
    hits = find_doc_references(chunks, "get")
    assert hits == [], "word-boundary matching must prevent 'get' from matching inside 'budget'/'target'"


def test_matches_function_mentioned_in_backticks():
    chunks = parse_markdown_chunks(SAMPLE_README)
    hits = find_doc_references(chunks, "greet")
    assert len(hits) >= 1
