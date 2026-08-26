"""Unit tests for src/fidelity/document_model.py structural parsing."""

from __future__ import annotations

from src.fidelity.document_model import CheckStatus, parse_document


class TestMarkdownParsing:
    def test_headings_captured_in_order(self):
        text = "# Title\n\nSome text.\n\n## Section A\n\nMore text.\n\n## Section B\n\nEnd.\n"
        doc = parse_document(text, format_hint="markdown")
        assert [h.text for h in doc.headings] == ["Title", "Section A", "Section B"]
        assert doc.section_order() == ("Title", "Section A", "Section B")

    def test_paragraphs_associated_with_nearest_heading(self):
        text = "## Section A\n\nParagraph one.\n\nParagraph two.\n"
        doc = parse_document(text, format_hint="markdown")
        assert len(doc.paragraphs) == 2
        assert all(p.heading_context == "Section A" for p in doc.paragraphs)

    def test_table_parsed_into_header_and_cells(self):
        text = (
            "## Schedule A — Rate Card\n\n"
            "| Destination | Prefix | Rate (USD/min) |\n"
            "| --- | --- | --- |\n"
            "| United States | 1 | 0.0039 |\n"
            "| United Kingdom | 44 | 0.0061 |\n"
        )
        doc = parse_document(text, format_hint="markdown")
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert table.header_row == ("Destination", "Prefix", "Rate (USD/min)")
        assert table.heading_context == "Schedule A — Rate Card"
        cell_map = table.cell_map()
        assert cell_map[(0, 0)] == "United States"
        assert cell_map[(1, 2)] == "0.0061"

    def test_table_not_absorbed_into_paragraphs(self):
        text = "## S\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nAfter-table paragraph.\n"
        doc = parse_document(text, format_hint="markdown")
        assert len(doc.tables) == 1
        assert len(doc.paragraphs) == 1
        assert doc.paragraphs[0].text == "After-table paragraph."

    def test_headers_footers_footnotes_marked_not_applicable_for_markdown(self):
        doc = parse_document("# T\n\nBody.\n", format_hint="markdown")
        for check in (doc.headers, doc.footers, doc.footnotes):
            assert check.status == CheckStatus.NOT_APPLICABLE
            assert check.reason  # never silently empty

    def test_sha256_is_stable_and_content_dependent(self):
        a = parse_document("hello", format_hint="txt")
        b = parse_document("hello", format_hint="txt")
        c = parse_document("hello!", format_hint="txt")
        assert a.sha256 == b.sha256
        assert a.sha256 != c.sha256


class TestHtmlParsing:
    def test_html_headings_and_table(self):
        html = (
            "<h2>Schedule A — Rate Card</h2>"
            '<table style="width:100%"><thead><tr><th>Destination</th><th>Rate</th></tr></thead>'
            "<tbody><tr><td>United States</td><td>0.0039</td></tr></tbody></table>"
        )
        doc = parse_document(html, format_hint="html")
        assert [h.text for h in doc.headings] == ["Schedule A — Rate Card"]
        assert len(doc.tables) == 1
        assert doc.tables[0].header_row == ("Destination", "Rate")
        assert doc.tables[0].cell_map()[(0, 0)] == "United States"
        assert doc.styles == ("width:100%",)
        assert doc.headers.status == CheckStatus.NOT_APPLICABLE

    def test_html_paragraphs_outside_tables_and_headings(self):
        html = "<h1>T</h1><p>First paragraph.</p><p>Second paragraph.</p>"
        doc = parse_document(html, format_hint="html")
        assert [p.text for p in doc.paragraphs] == ["First paragraph.", "Second paragraph."]


class TestPlainTextParsing:
    def test_paragraphs_split_on_blank_lines(self):
        text = "Para one.\n\nPara two.\n\n\nPara three.\n"
        doc = parse_document(text, format_hint="txt")
        assert [p.text for p in doc.paragraphs] == ["Para one.", "Para two.", "Para three."]
        assert doc.headings == tuple()
        assert doc.tables == tuple()
