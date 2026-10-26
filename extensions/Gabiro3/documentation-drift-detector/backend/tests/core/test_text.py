"""Search reads a text projection of chunk HTML, not the markup.

Matching against the stored HTML would make "class", "href" or "p" hit every
chunk that has a tag, and would miss any phrase interrupted by an inline one.
"""

from core.text import html_to_text, snippet_around


class TestHtmlToText:
    def test_strips_tags(self):
        assert html_to_text("<p>Run <code>npm install</code></p>") == "Run npm install"

    def test_tag_names_and_attributes_are_not_searchable_text(self):
        """The whole point: a query for 'class' must not match every chunk."""
        text = html_to_text('<p class="intro" href="#x">hello</p>')
        assert text == "hello"
        assert "class" not in text and "href" not in text

    def test_tags_become_spaces_so_cells_do_not_fuse(self):
        """<td>a</td><td>b</td> must read as 'a b', never 'ab' — a fused word
        appears nowhere in the document and matches nothing a user would type."""
        assert html_to_text("<td>alpha</td><td>beta</td>") == "alpha beta"

    def test_collapses_whitespace(self):
        assert html_to_text("<p>a\n\n   b</p>") == "a b"

    def test_decodes_the_entities_superdocs_emits(self):
        assert html_to_text("<p>a&nbsp;&amp;&nbsp;b</p>") == "a & b"

    def test_empty_and_none_are_empty(self):
        assert html_to_text("") == ""
        assert html_to_text(None) == ""

    def test_text_without_markup_survives_unchanged(self):
        assert html_to_text("plain text") == "plain text"


class TestSnippetAround:
    TEXT = "alpha beta gamma delta epsilon zeta eta theta"

    def test_offsets_point_at_the_match_inside_the_snippet(self):
        index = self.TEXT.index("gamma")
        snip = snippet_around(self.TEXT, index, len("gamma"), radius=6)
        start = snip["match_start"]
        assert snip["text"][start:start + snip["match_length"]] == "gamma"

    def test_marks_truncation_at_both_ends(self):
        index = self.TEXT.index("delta")
        snip = snippet_around(self.TEXT, index, 5, radius=4)
        assert snip["text"].startswith("…") and snip["text"].endswith("…")

    def test_short_text_is_not_truncated(self):
        snip = snippet_around("alpha beta", 0, 5, radius=90)
        assert snip["text"] == "alpha beta"
        assert snip["match_start"] == 0

    def test_no_match_yields_a_leading_window_with_no_highlight(self):
        """Semantic hits contain no literal match, so there is nothing to mark
        and the snippet must not invent a highlight."""
        snip = snippet_around(self.TEXT, -1, 0)
        assert snip["match_start"] == -1
        assert snip["match_length"] == 0
        assert snip["text"].startswith("alpha")

    def test_offset_accounts_for_the_leading_ellipsis(self):
        index = self.TEXT.index("epsilon")
        snip = snippet_around(self.TEXT, index, len("epsilon"), radius=5)
        start = snip["match_start"]
        assert snip["text"][start:start + snip["match_length"]] == "epsilon"
