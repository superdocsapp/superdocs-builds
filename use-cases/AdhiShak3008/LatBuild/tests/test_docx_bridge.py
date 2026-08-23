"""
test_docx_bridge.py
Tests for prose ↔ .docx roundtrip conversion.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

from docx_bridge import prose_to_docx, extract_text_from_docx, extract_text_from_html


class TestProseToDocx:

    def test_returns_bytes(self):
        result = prose_to_docx("Hello world.")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_valid_docx_header(self):
        result = prose_to_docx("Test content.")
        # DOCX files start with PK (zip archive)
        assert result[:2] == b'PK'

    def test_empty_text_still_produces_docx(self):
        result = prose_to_docx("")
        assert isinstance(result, bytes)
        assert result[:2] == b'PK'

    def test_multi_paragraph_text(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = prose_to_docx(text)
        assert isinstance(result, bytes)
        assert len(result) > 100


class TestExtractTextFromDocx:

    def test_roundtrip_single_paragraph(self):
        text = "We present a novel approach to PDF editing."
        docx_bytes = prose_to_docx(text)
        recovered = extract_text_from_docx(docx_bytes)
        assert text in recovered

    def test_roundtrip_multi_paragraph(self):
        text = "First paragraph with content.\n\nSecond paragraph with more content."
        docx_bytes = prose_to_docx(text)
        recovered = extract_text_from_docx(docx_bytes)
        assert "First paragraph" in recovered
        assert "Second paragraph" in recovered

    def test_roundtrip_preserves_numbers(self):
        text = "Accuracy: 94.2% (p < 0.001, n=120, F(2,497)=14.3)"
        docx_bytes = prose_to_docx(text)
        recovered = extract_text_from_docx(docx_bytes)
        assert "94.2" in recovered
        assert "0.001" in recovered

    def test_roundtrip_preserves_citations(self):
        text = "As shown in previous work [1,2,3] and (Smith et al., 2020)."
        docx_bytes = prose_to_docx(text)
        recovered = extract_text_from_docx(docx_bytes)
        assert "[1,2,3]" in recovered or "1,2,3" in recovered


class TestExtractTextFromHtml:

    def test_strips_tags(self):
        html = "<p>Hello <strong>world</strong>.</p>"
        result = extract_text_from_html(html)
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_multiple_paragraphs(self):
        html = "<p>First.</p><p>Second.</p>"
        result = extract_text_from_html(html)
        assert "First" in result
        assert "Second" in result

    def test_empty_html(self):
        result = extract_text_from_html("")
        assert result == ""

    def test_script_tags_stripped(self):
        html = "<p>Content</p><script>alert('x')</script>"
        result = extract_text_from_html(html)
        assert "alert" not in result
        assert "Content" in result

    def test_heading_tags_produce_paragraphs(self):
        html = "<h1>Title</h1><p>Body text.</p>"
        result = extract_text_from_html(html)
        assert "Title" in result
        assert "Body text" in result
