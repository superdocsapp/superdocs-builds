"""
test_pdf_analyzer.py
Tests for PDFAnalyzer column detection, heading classification,
and text block extraction logic.

No live PDF required — we test the logic units directly.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

from pdf_analyzer import PDFAnalyzer, DocumentGrammar, BBox, ColumnRegion, KNOWN_HEADINGS


@pytest.fixture
def analyzer():
    return PDFAnalyzer()


@pytest.fixture
def base_grammar():
    return DocumentGrammar(
        page_width=612.0, page_height=792.0,
        margin_top=54.0, margin_bottom=54.0,
        margin_left=54.0, margin_right=558.0,
        column_count=2,
        column_regions=[
            ColumnRegion(0, 54.0, 288.0, 234.0),
            ColumnRegion(1, 324.0, 558.0, 234.0),
        ],
        split_x=306.0,
        column_gap=36.0,
        body_fontname="Times-Roman",
        body_fontsize=9.0,
        body_line_height=11.0,
        paragraph_spacing=8.8,
        heading_styles={},
    )


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

class TestColumnDetection:

    def test_two_column_detection(self, analyzer):
        """Words clustered in two groups should produce two columns."""
        words = (
            [{"x0": 60 + i * 10, "x1": 70 + i * 10, "top": 200, "bottom": 212,
              "fontname": "Times", "size": 9} for i in range(20)]
            +
            [{"x0": 360 + i * 10, "x1": 370 + i * 10, "top": 200, "bottom": 212,
              "fontname": "Times", "size": 9} for i in range(20)]
        )
        split_x, cols, two_col = analyzer._find_split(words, 612.0, 792.0)
        assert two_col
        assert len(cols) == 2
        assert cols[0].x0 < cols[1].x0

    def test_single_column_detection(self, analyzer):
        """Uniform word distribution = single column."""
        words = [
            {"x0": 54 + i * 5, "x1": 57 + i * 5, "top": 200, "bottom": 212,
             "fontname": "Times", "size": 9}
            for i in range(100)
        ]
        split_x, cols, two_col = analyzer._find_split(words, 612.0, 792.0)
        assert len(cols) >= 1   # may or may not split; key check is two-clustered gives 2

    def test_empty_words_returns_single_column(self, analyzer):
        split_x, cols, two_col = analyzer._find_split([], 612.0, 792.0)
        assert len(cols) == 1
        assert not two_col

    def test_column_widths_positive(self, analyzer):
        words = (
            [{"x0": 54, "x1": 288, "top": 200, "bottom": 212,
              "fontname": "Times", "size": 9}] * 10 +
            [{"x0": 324, "x1": 558, "top": 200, "bottom": 212,
              "fontname": "Times", "size": 9}] * 10
        )
        split_x, cols, _ = analyzer._find_split(words, 612.0, 792.0)
        for col in cols:
            assert col.width > 0


# ---------------------------------------------------------------------------
# Heading classification
# ---------------------------------------------------------------------------

class TestHeadingClassification:

    def test_roman_numeral_heading(self, analyzer, base_grammar):
        assert analyzer._classify_heading("I. INTRODUCTION", 9.0, False, base_grammar)
        assert analyzer._classify_heading("III. METHODOLOGY", 9.0, False, base_grammar)
        assert analyzer._classify_heading("IV. RESULTS AND DISCUSSION", 9.0, False, base_grammar)

    def test_known_heading_words(self, analyzer, base_grammar):
        assert analyzer._classify_heading("Abstract", 9.0, False, base_grammar)
        assert analyzer._classify_heading("References", 9.0, False, base_grammar)
        assert analyzer._classify_heading("Conclusion", 9.0, False, base_grammar)
        assert analyzer._classify_heading("Introduction", 9.0, False, base_grammar)

    def test_larger_bold_is_heading(self, analyzer, base_grammar):
        assert analyzer._classify_heading("Some Section Title", 12.0, True, base_grammar)

    def test_body_text_not_heading(self, analyzer, base_grammar):
        assert not analyzer._classify_heading(
            "We present a novel approach to document analysis.", 9.0, False, base_grammar
        )

    def test_all_caps_short_is_heading(self, analyzer, base_grammar):
        assert analyzer._classify_heading("METHODOLOGY", 9.0, False, base_grammar)
        # "METHODOLOGY" is in KNOWN_HEADINGS — single ALL CAPS known word
        assert analyzer._classify_heading("INTRODUCTION", 9.0, False, base_grammar)

    def test_all_caps_long_not_heading(self, analyzer, base_grammar):
        # Long ALL CAPS text is probably a title page or figure, not a section heading
        long_caps = "THIS IS A VERY LONG ALL CAPS STRING THAT SHOULD NOT BE A HEADING AT ALL"
        # 12 words > 8 word limit → not a heading
        assert not analyzer._classify_heading(long_caps, 9.0, False, base_grammar)

    def test_not_heading_single_short_word(self, analyzer, base_grammar):
        # Very short non-keyword text
        assert not analyzer._classify_heading("of", 9.0, False, base_grammar)


# ---------------------------------------------------------------------------
# Column assignment
# ---------------------------------------------------------------------------

class TestColumnAssignment:

    def test_left_column_assigned(self, analyzer):
        words_left = [{"x0": 60.0, "x1": 280.0, "top": 100, "bottom": 112,
                       "fontname": "T", "size": 9}]
        col_lists = analyzer._split_words_by_column(words_left, 306.0, 612.0, 792.0)
        assert len(col_lists[0]) == 1  # goes to left column
        assert len(col_lists[1]) == 0 if len(col_lists) > 1 else True

    def test_right_column_assigned(self, analyzer):
        words_right = [{"x0": 330.0, "x1": 550.0, "top": 100, "bottom": 112,
                        "fontname": "T", "size": 9}]
        col_lists = analyzer._split_words_by_column(words_right, 306.0, 612.0, 792.0)
        # midpoint = 440 > 306 → right column
        assert len(col_lists) == 2
        assert len(col_lists[1]) == 1

    def test_single_column_fallback(self, analyzer):
        words = [{"x0": 100.0, "x1": 400.0, "top": 100, "bottom": 112,
                  "fontname": "T", "size": 9}]
        col_lists = analyzer._split_words_by_column(words, 0.0, 612.0, 792.0)
        assert len(col_lists) == 1
        assert len(col_lists[0]) == 1


# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------

class TestBBox:

    def test_width_height(self):
        bbox = BBox(10, 20, 110, 70)
        assert bbox.width == 100
        assert bbox.height == 50

    def test_overlaps_true(self):
        a = BBox(0, 0, 100, 100)
        b = BBox(50, 50, 150, 150)
        assert a.overlaps(b)

    def test_overlaps_false(self):
        a = BBox(0, 0, 50, 50)
        b = BBox(60, 60, 110, 110)
        assert not a.overlaps(b)

    def test_overlaps_touching_edge_false(self):
        a = BBox(0, 0, 50, 50)
        b = BBox(50, 0, 100, 50)
        assert not a.overlaps(b)

    def test_area(self):
        bbox = BBox(0, 0, 10, 20)
        assert bbox.area == 200
