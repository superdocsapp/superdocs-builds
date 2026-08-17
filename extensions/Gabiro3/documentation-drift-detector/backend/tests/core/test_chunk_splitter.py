from core.superdocs_client import split_chunked_html


class TestSplitChunkedHtml:
    """The chunk splitter turns SuperDocs' chunked HTML into the records we
    persist. If it drops content, documents render blank and the edit
    protocol loses its addressing scheme — so pin the behaviour down."""

    def test_splits_top_level_elements(self):
        html = (
            '<h1 data-chunk-id="a1">Getting Started</h1>\n'
            '<p data-chunk-id="b2">Run npm install.</p>'
        )
        chunks = split_chunked_html(html)
        assert [c["chunk_id"] for c in chunks] == ["a1", "b2"]

    def test_preserves_full_outer_html(self):
        html = '<h1 data-chunk-id="a1">Getting Started</h1>'
        chunks = split_chunked_html(html)
        assert chunks[0]["html"] == '<h1 data-chunk-id="a1">Getting Started</h1>'

    def test_preserves_nested_inline_markup(self):
        html = '<p data-chunk-id="b2">Run <code>npm install</code> first.</p>'
        chunks = split_chunked_html(html)
        assert "<code>npm install</code>" in chunks[0]["html"]

    def test_no_chunk_is_empty(self):
        html = (
            '<h1 data-chunk-id="a1">Title</h1>\n'
            '<p data-chunk-id="b2">Body text.</p>\n'
            '<h2 data-chunk-id="c3">Section</h2>'
        )
        chunks = split_chunked_html(html)
        assert len(chunks) == 3
        assert all(c["html"].strip() for c in chunks)

    def test_every_chunk_gets_a_content_hash(self):
        html = '<p data-chunk-id="b2">Body.</p>'
        chunks = split_chunked_html(html)
        assert len(chunks[0]["content_hash"]) == 64

    def test_differing_content_hashes_differ(self):
        a = split_chunked_html('<p data-chunk-id="x">one</p>')[0]
        b = split_chunked_html('<p data-chunk-id="x">two</p>')[0]
        assert a["content_hash"] != b["content_hash"]

    def test_html_without_chunk_ids_is_not_dropped(self):
        chunks = split_chunked_html("<p>no chunk id here</p>")
        assert len(chunks) == 1
        assert "no chunk id here" in chunks[0]["html"]

    def test_empty_input_yields_no_chunks(self):
        assert split_chunked_html("") == []

    def test_self_closing_tags_inside_chunk(self):
        html = '<p data-chunk-id="b2">line<br/>break</p>'
        chunks = split_chunked_html(html)
        assert len(chunks) == 1
        assert "break" in chunks[0]["html"]
