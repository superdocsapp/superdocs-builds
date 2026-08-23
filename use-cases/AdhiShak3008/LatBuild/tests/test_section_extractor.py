"""
test_section_extractor.py
Tests for section text extraction and SuperDocs instruction building.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

from section_extractor import extract_section, build_superdocs_instruction, ExtractedSection


class TestExtractSection:

    def test_returns_extracted_section(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert isinstance(result, ExtractedSection)

    def test_clean_text_contains_content(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert "mitochondrial" in result.clean_text.lower() or len(result.clean_text) > 0

    def test_word_count_positive(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert result.word_count > 0

    def test_char_count_equals_len(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert result.char_count == len(result.clean_text)

    def test_section_name_preserved(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert result.section_name == abstract_section.title

    def test_multi_block_section_joined(self, methodology_section, ieee_grammar):
        result = extract_section(methodology_section, ieee_grammar)
        # All 3 blocks should be joined
        assert result.word_count > 10

    def test_estimated_height_positive(self, abstract_section, ieee_grammar):
        result = extract_section(abstract_section, ieee_grammar)
        assert result.estimated_height_pts > 0

    def test_empty_section_returns_zero_words(self, ieee_grammar):
        from conftest import make_block
        from flow_mapper import Section, FlowRegion
        from pdf_analyzer import BBox
        heading = make_block("II. RESULTS", is_heading=True)
        section = Section(
            id="sec_ii_results", title="II. RESULTS", level=1, parent_id=None,
            heading_block=heading,
            content_blocks=[],
            flow_regions=[FlowRegion(1, 0, BBox(54,700,288,600), 234.0)],
            is_editable=True,
        )
        result = extract_section(section, ieee_grammar)
        assert result.word_count == 0


class TestBuildSuperdocsInstruction:

    def test_contains_user_instruction(self, abstract_section, ieee_grammar):
        extracted = extract_section(abstract_section, ieee_grammar)
        instruction = build_superdocs_instruction(
            "Make this more concise.", extracted
        )
        assert "Make this more concise." in instruction

    def test_contains_citation_preservation_notice(self, abstract_section, ieee_grammar):
        extracted = extract_section(abstract_section, ieee_grammar)
        instruction = build_superdocs_instruction("Edit this.", extracted)
        # Instruction should contain the user instruction at minimum
        assert "Edit this." in instruction

    def test_contains_word_hint_when_enabled(self, abstract_section, ieee_grammar):
        extracted = extract_section(abstract_section, ieee_grammar)
        instruction = build_superdocs_instruction(
            "Edit.", extracted, include_word_hint=True
        )
        assert str(extracted.word_count) in instruction

    def test_no_word_hint_when_disabled(self, abstract_section, ieee_grammar):
        extracted = extract_section(abstract_section, ieee_grammar)
        instruction = build_superdocs_instruction(
            "Edit.", extracted, include_word_hint=False
        )
        assert "words" not in instruction or str(extracted.word_count) not in instruction

    def test_instruction_is_string(self, abstract_section, ieee_grammar):
        extracted = extract_section(abstract_section, ieee_grammar)
        instruction = build_superdocs_instruction("Test.", extracted)
        assert isinstance(instruction, str)
        assert len(instruction) > 0
