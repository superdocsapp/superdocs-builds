"""
test_flow_mapper.py
Tests for FlowMapper section detection, flow region building,
and DocumentFlowMap construction.
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

from pdf_analyzer import BBox, TextBlock, ColumnRegion
from flow_mapper import FlowMapper, Section, FlowRegion, DocumentFlowMap, NON_EDITABLE
from conftest import make_block


@pytest.fixture
def mapper():
    return FlowMapper()


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

class TestSectionDetection:

    def test_detects_sections_from_headings(self, mapper, ieee_grammar):
        blocks = [
            make_block("Abstract", fontname="Times-Bold", is_bold=True, is_heading=True, ro=0),
            make_block("We investigate mitochondrial dynamics.", ro=1),
            make_block("I. INTRODUCTION", fontname="Times-Bold", is_bold=True, is_heading=True, ro=2),
            make_block("Parkinson's disease affects 1% of adults.", ro=3),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        titles = [s.title for s in sections]
        assert any("Abstract" in t for t in titles)
        assert any("Introduction" in t or "I." in t for t in titles)

    def test_content_assigned_to_correct_section(self, mapper, ieee_grammar):
        blocks = [
            make_block("Abstract", is_heading=True, ro=0),
            make_block("Abstract body text.", ro=1),
            make_block("I. INTRODUCTION", is_heading=True, ro=2),
            make_block("Introduction body text.", ro=3),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        abstract = next(s for s in sections if "Abstract" in s.title)
        assert len(abstract.content_blocks) == 1
        assert "Abstract body text" in abstract.content_blocks[0].text

    def test_references_not_editable(self, mapper, ieee_grammar):
        blocks = [
            make_block("References", is_heading=True, ro=0),
            make_block("[1] Smith et al. 2020.", ro=1),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        refs = next((s for s in sections if "reference" in s.title.lower()), None)
        assert refs is not None
        assert not refs.is_editable

    def test_preamble_before_first_heading_not_editable(self, mapper, ieee_grammar):
        blocks = [
            make_block("Title of the Paper", ro=0),
            make_block("Author Name", ro=1),
            make_block("Abstract", is_heading=True, ro=2),
            make_block("We study...", ro=3),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        preamble = sections[0]
        assert not preamble.is_editable

    def test_no_headings_returns_single_section(self, mapper, ieee_grammar):
        blocks = [
            make_block("Some text.", ro=0),
            make_block("More text.", ro=1),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        assert len(sections) == 1

    def test_caption_blocks_filtered_out(self, mapper, ieee_grammar):
        blocks = [
            make_block("Abstract", is_heading=True, ro=0),
            make_block("We study mitochondria.", ro=1),
            make_block("Fig. 1. Example figure.", ro=2),
            make_block("Table 1. Results.", ro=3),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        abstract = next(s for s in sections if "Abstract" in s.title)
        texts = [b.text for b in abstract.content_blocks]
        assert not any("Fig." in t or "Table" in t for t in texts)


# ---------------------------------------------------------------------------
# Flow region building
# ---------------------------------------------------------------------------

class TestFlowRegionBuilding:

    def test_single_block_single_region(self, mapper, ieee_grammar, abstract_section):
        regions = mapper._build_flow_regions(abstract_section, ieee_grammar)
        assert len(regions) == 1

    def test_multi_page_section_multiple_regions(self, mapper, ieee_grammar, methodology_section):
        regions = mapper._build_flow_regions(methodology_section, ieee_grammar)
        assert len(regions) == 3

    def test_flow_region_page_correct(self, mapper, ieee_grammar, abstract_section):
        regions = mapper._build_flow_regions(abstract_section, ieee_grammar)
        assert regions[0].page == 1

    def test_empty_section_returns_single_default_region(self, mapper, ieee_grammar):
        heading = make_block("II. RESULTS", is_heading=True, ro=5)
        section = Section(
            id="sec_ii_results", title="II. RESULTS", level=1, parent_id=None,
            heading_block=heading,
            content_blocks=[],
            flow_regions=[],
            is_editable=True,
        )
        regions = mapper._build_flow_regions(section, ieee_grammar)
        assert len(regions) == 1

    def test_regions_have_positive_dimensions(self, mapper, ieee_grammar, methodology_section):
        regions = mapper._build_flow_regions(methodology_section, ieee_grammar)
        for r in regions:
            assert r.bbox.width > 0
            assert r.bbox.height > 0


# ---------------------------------------------------------------------------
# DocumentFlowMap
# ---------------------------------------------------------------------------

class TestDocumentFlowMap:

    def test_get_section_by_name(self, simple_flow_map, abstract_section):
        result = simple_flow_map.get_section("Abstract")
        assert result is not None
        assert result.title == "Abstract"

    def test_get_section_missing_returns_none(self, simple_flow_map):
        assert simple_flow_map.get_section("Nonexistent Section") is None

    def test_editable_sections_excludes_references(self, simple_flow_map):
        editable = simple_flow_map.editable_sections()
        titles = [s.title for s in editable]
        assert all("reference" not in t.lower() for t in titles)

    def test_sections_after(self, simple_flow_map, abstract_section, methodology_section):
        after = simple_flow_map.sections_after(abstract_section)
        titles = [s.title for s in after]
        assert "III. METHODOLOGY" in titles

    def test_sections_after_last_section_is_empty(self, simple_flow_map, references_section):
        after = simple_flow_map.sections_after(references_section)
        assert after == []

    def test_hierarchy_level_detection(self, mapper, ieee_grammar):
        """Level-1 sections come before level-2 subsections."""
        blocks = [
            make_block("I. INTRODUCTION", is_heading=True, ro=0),
            make_block("Body text.", ro=1),
            make_block("A. Background", is_heading=True, ro=2),
            make_block("Subsection text.", ro=3),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        intro = next(s for s in sections if "I." in s.title)
        sub = next(s for s in sections if "A." in s.title)
        assert intro.level == 1
        assert sub.level == 2
        assert sub.parent_id == intro.id

    def test_children_of(self, mapper, ieee_grammar):
        """children_of returns all level-2 sections under a level-1 parent."""
        blocks = [
            make_block("I. INTRODUCTION", is_heading=True, ro=0),
            make_block("Body.", ro=1),
            make_block("A. Background", is_heading=True, ro=2),
            make_block("Sub text.", ro=3),
            make_block("B. Related", is_heading=True, ro=4),
            make_block("More text.", ro=5),
        ]
        sections = mapper._detect_sections(blocks, ieee_grammar)
        fm = DocumentFlowMap(grammar=ieee_grammar, sections=sections,
                             all_blocks=blocks, non_content=[])
        intro = next(s for s in sections if "I." in s.title)
        children = fm.children_of(intro)
        assert len(children) == 2
