"""
conftest.py
Shared fixtures for LatBuild tests.
All tests run without a live PDF or SuperDocs API key.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

import pytest
from pdf_analyzer import (  # type: ignore
    BBox, TextBlock, NonContentElement, ColumnRegion,
    DocumentGrammar, AnalyzedDocument, PageLayout
)
from flow_mapper import Section, FlowRegion, DocumentFlowMap  # type: ignore


# ---------------------------------------------------------------------------
# Grammar fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ieee_grammar():
    """Realistic DocumentGrammar for a two-column IEEE paper."""
    return DocumentGrammar(
        page_width=612.0,
        page_height=792.0,
        margin_top=54.0,
        margin_bottom=54.0,
        margin_left=54.0,
        margin_right=54.0,
        column_count=2,
        column_regions=[
            ColumnRegion(index=0, x0=54.0, x1=288.0, width=234.0),
            ColumnRegion(index=1, x0=324.0, x1=558.0, width=234.0),
        ],
        split_x=306.0,
        column_gap=36.0,
        body_fontname="Times-Roman",
        body_fontsize=9.0,
        body_line_height=11.0,
        paragraph_spacing=8.8,
        heading_styles={
            "h1": {"fontname": "Times-Bold", "fontsize": 10.0, "is_bold": True},
        },
    )


# ---------------------------------------------------------------------------
# TextBlock factory
# ---------------------------------------------------------------------------

def make_block(text, page=1, col=0, y0=100.0, y1=150.0, fontsize=9.0,
               fontname="Times-Roman", is_bold=False, is_heading=False, ro=0):
    top = min(float(y0), float(y1))
    bot = max(float(y0), float(y1))
    return TextBlock(
        text=text,
        bbox=BBox(x0=54.0, y0=top, x1=288.0, y1=bot),
        page=page,
        column=col,
        fontname=fontname,
        fontsize=fontsize,
        is_bold=is_bold,
        is_heading=is_heading,
        reading_order=ro,
        line_height=11.0,
    )


# ---------------------------------------------------------------------------
# Section fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def abstract_section(ieee_grammar):
    heading = make_block("Abstract", y0=100.0, y1=112.0, fontname="Times-Bold",
                         is_bold=True, is_heading=True, ro=0)
    content = make_block(
        "We present a novel framework for mitochondrial dynamics analysis. "
        "Our method achieves 94.2% accuracy (p < 0.001, n=120) on three benchmarks. "
        "The system processes documents in under 2 seconds on standard hardware.",
        y0=115.0, y1=180.0, ro=1
    )
    region = FlowRegion(
        page=1, column=0,
        bbox=BBox(x0=54.0, y0=115.0, x1=288.0, y1=180.0),
        column_width=234.0,
        heading_bottom_y=112.0,
    )
    return Section(
        id="abstract", title="Abstract", level=1, parent_id=None,
        heading_block=heading,
        content_blocks=[content],
        flow_regions=[region],
        is_editable=True,
    )


@pytest.fixture
def methodology_section(ieee_grammar):
    heading = make_block("III. METHODOLOGY", page=3, col=0, y0=100.0, y1=112.0,
                         fontname="Times-Bold", is_bold=True, is_heading=True, ro=10)
    blocks = [
        make_block("We collected 500 samples from three independent datasets.",
                   page=3, col=0, y0=115.0, y1=150.0, ro=11),
        make_block("Each sample was processed using our pipeline described in [3].",
                   page=3, col=1, y0=100.0, y1=140.0, ro=12),
        make_block("Statistical analysis was performed with ANOVA (F(2,497)=14.3, p<0.001).",
                   page=4, col=0, y0=100.0, y1=145.0, ro=13),
    ]
    regions = [
        FlowRegion(page=3, column=0, bbox=BBox(54, 115, 288, 150), column_width=234.0, heading_bottom_y=112.0),
        FlowRegion(page=3, column=1, bbox=BBox(324, 100, 558, 140), column_width=234.0),
        FlowRegion(page=4, column=0, bbox=BBox(54, 100, 288, 145), column_width=234.0),
    ]
    return Section(
        id="sec_iii_methodology", title="III. METHODOLOGY", level=1, parent_id=None,
        heading_block=heading,
        content_blocks=blocks,
        flow_regions=regions,
        is_editable=True,
    )


@pytest.fixture
def references_section():
    heading = make_block("References", page=11, col=0, y0=100.0, y1=112.0,
                         is_heading=True, ro=90)
    content = make_block("[1] Smith, J. et al. Nature 2020.", page=11, col=0,
                         y0=115.0, y1=130.0, ro=91)
    return Section(
        id="references", title="References", level=1, parent_id=None,
        heading_block=heading,
        content_blocks=[content],
        flow_regions=[
            FlowRegion(page=11, column=0, bbox=BBox(54, 115, 288, 130), column_width=234.0, heading_bottom_y=112.0)
        ],
        is_editable=False,
    )


@pytest.fixture
def simple_flow_map(ieee_grammar, abstract_section, methodology_section, references_section):
    all_blocks = (
        ([abstract_section.heading_block] + abstract_section.content_blocks) +
        ([methodology_section.heading_block] + methodology_section.content_blocks) +
        ([references_section.heading_block] + references_section.content_blocks)
    )
    return DocumentFlowMap(
        grammar=ieee_grammar,
        sections=[abstract_section, methodology_section, references_section],
        all_blocks=all_blocks,
        non_content=[],
    )


# ---------------------------------------------------------------------------
# Non-content fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def figure_on_page3():
    return NonContentElement(
        type="image",
        page=3,
        bbox=BBox(x0=324.0, y0=300.0, x1=558.0, y1=400.0),
        anchor="absolute",
    )
