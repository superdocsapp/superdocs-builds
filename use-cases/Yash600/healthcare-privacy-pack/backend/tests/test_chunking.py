"""
Pure-function tests for chunking.py -- chunk extraction, heading
extraction, content hashing, and citation parsing. No live SuperDocs key,
no database, no network access required.
"""

import chunking


class TestExtractChunks:
    def test_simple_two_chunks(self):
        html = (
            '<div data-chunk-id="a"><p>hi</p></div>'
            '<div data-chunk-id="b"><p>bye</p></div>'
        )
        chunks = chunking.extract_chunks(html)
        assert chunks == {"a": "<p>hi</p>", "b": "<p>bye</p>"}

    def test_preserves_nested_elements(self):
        html = '<div data-chunk-id="sec-1"><h2>Title</h2><p>Some <b>bold</b> and <i>italic</i>.</p></div>'
        chunks = chunking.extract_chunks(html)
        assert "sec-1" in chunks
        assert "<h2>Title</h2>" in chunks["sec-1"]
        assert "<b>bold</b>" in chunks["sec-1"]

    def test_nested_divs_inside_a_chunk_dont_terminate_early(self):
        # A chunk containing an inner <div> (e.g. a nested list wrapper)
        # must not be cut off at the first </div> -- depth tracking handles this.
        html = '<div data-chunk-id="x"><div class="inner"><p>nested</p></div><p>after</p></div>'
        chunks = chunking.extract_chunks(html)
        assert "nested" in chunks["x"]
        assert "after" in chunks["x"]

    def test_no_chunks_returns_empty_dict(self):
        assert chunking.extract_chunks("<p>no chunk ids here</p>") == {}

    def test_real_shape_policy_and_procedure_documents(self):
        # Mirrors the actual shape SuperDocs returns for this project:
        # sibling top-level chunk divs, not nested.
        html = (
            '<div data-chunk-id="policy-sec-1"><h2>Access Control and Authentication</h2>'
            "<p>Policy text.</p></div>"
            '<div data-chunk-id="policy-sec-2"><h2>Individual Rights</h2><p>More text.</p></div>'
        )
        chunks = chunking.extract_chunks(html)
        assert set(chunks.keys()) == {"policy-sec-1", "policy-sec-2"}


class TestNormalizeText:
    def test_strips_tags(self):
        assert chunking.normalize_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_collapses_whitespace(self):
        assert chunking.normalize_text("Hello   \n\n  world") == "Hello world"

    def test_decodes_common_entities(self):
        assert chunking.normalize_text("A &mdash; B &amp; C") == "A — B & C"


class TestContentHash:
    def test_stable_across_whitespace_and_attribute_changes(self):
        a = '<div data-chunk-id="x"><h2>Title</h2><p>Some  text.</p></div>'
        b = '<div data-chunk-id="x"   ><h2>Title</h2><p>Some text.</p></div>'
        chunks_a = chunking.extract_chunks(a)
        chunks_b = chunking.extract_chunks(b)
        assert chunking.content_hash(chunks_a["x"]) == chunking.content_hash(chunks_b["x"])

    def test_changes_when_visible_text_changes(self):
        a = '<div data-chunk-id="x"><p>60 hours</p></div>'
        b = '<div data-chunk-id="x"><p>24 hours</p></div>'
        chunks_a = chunking.extract_chunks(a)
        chunks_b = chunking.extract_chunks(b)
        assert chunking.content_hash(chunks_a["x"]) != chunking.content_hash(chunks_b["x"])

    def test_is_deterministic(self):
        html = "<p>Same content every time.</p>"
        assert chunking.content_hash(html) == chunking.content_hash(html)

    def test_returns_hex_sha256(self):
        digest = chunking.content_hash("<p>anything</p>")
        assert len(digest) == 64
        int(digest, 16)  # raises if not valid hex


class TestExtractFirstHeading:
    def test_finds_h2(self):
        assert chunking.extract_first_heading("<h2>Breach Notification</h2><p>...</p>") == "Breach Notification"

    def test_finds_first_of_multiple_headings(self):
        html = "<h2>First</h2><p>x</p><h3>Second</h3>"
        assert chunking.extract_first_heading(html) == "First"

    def test_none_when_no_heading(self):
        assert chunking.extract_first_heading("<p>Implements: Policy §4 — Breach Notification</p>") is None

    def test_strips_inner_tags_from_heading(self):
        assert chunking.extract_first_heading("<h2>Section <em>4</em>: Breach</h2>") == "Section 4 : Breach"


class TestParseImplementsCitation:
    def test_valid_citation(self):
        result = chunking.parse_implements_citation("Implements: Policy §4 — Breach Notification")
        assert result == (4, "Breach Notification")

    def test_valid_citation_with_html_wrapper(self):
        result = chunking.parse_implements_citation(
            "<p><strong>Implements: Policy §1 — Access Control and Authentication</strong></p>"
        )
        assert result == (1, "Access Control and Authentication")

    def test_accepts_hyphen_as_dash_variant(self):
        result = chunking.parse_implements_citation("Implements: Policy §6 - Vendor Risk Review")
        assert result == (6, "Vendor Risk Review")

    def test_none_when_format_does_not_match(self):
        assert chunking.parse_implements_citation("This procedure covers access control.") is None

    def test_none_on_empty_string(self):
        assert chunking.parse_implements_citation("") is None


class TestIsStale:
    def test_matching_hashes_not_stale(self):
        assert chunking.is_stale("abc123", "abc123") is False

    def test_differing_hashes_is_stale(self):
        assert chunking.is_stale("abc123", "def456") is True

    def test_real_hashes_roundtrip(self):
        old_html = "<p>Breach notification must occur within 60 hours.</p>"
        new_html = "<p>Breach notification must occur within 24 hours.</p>"
        old_hash = chunking.content_hash(old_html)
        new_hash = chunking.content_hash(new_html)
        assert chunking.is_stale(old_hash, new_hash) is True
        # re-syncing against the same new content is no longer stale
        assert chunking.is_stale(new_hash, new_hash) is False
