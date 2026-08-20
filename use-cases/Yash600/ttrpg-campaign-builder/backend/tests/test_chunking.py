"""
test_chunking.py -- v2. chunking.py was reduced to two pure functions
(normalize_text, content_hash) when the data model moved from chunk-level
hashing to whole-document version numbers (see chunking.py's module
docstring). This replaces the old v1 suite, which tested chunk-parsing
functions that no longer exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chunking


def test_normalize_text_strips_tags_and_collapses_whitespace():
    assert chunking.normalize_text("<p>  Hello   <b>world</b>. </p>") == "Hello world ."


def test_normalize_text_handles_entities():
    assert chunking.normalize_text("<p>Salt &amp; pepper &mdash; to taste</p>") == "Salt & pepper — to taste"


def test_normalize_text_empty():
    assert chunking.normalize_text("") == ""
    assert chunking.normalize_text("<p></p>") == ""


def test_content_hash_stable_under_formatting_only_changes():
    a = chunking.content_hash('<p class="foo">Hello world</p>')
    b = chunking.content_hash("<p>Hello   world</p>")
    assert a == b


def test_content_hash_changes_with_real_content_changes():
    a = chunking.content_hash("<p>Hello world</p>")
    b = chunking.content_hash("<p>Hello there, world</p>")
    assert a != b


def test_content_hash_is_sha256_hex():
    h = chunking.content_hash("<p>anything</p>")
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex
