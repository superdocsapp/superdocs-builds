"""
Comprehensive unit and integration test suite for the LatBuild PDF reflow engine,
layout preservation invariants, multi-column text distribution, and transactional patcher.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

import tempfile
import pytest
import fitz

from pdf_analyzer import TextBlock, ColumnRegion, DocumentGrammar, BBox  # type: ignore
from flow_mapper import FlowRegion, Section, DocumentFlowMap  # type: ignore
from reflow_engine import ReflowEngine, SectionPatch, ReflowResult  # type: ignore
from pdf_patcher import apply_reflow, apply_multiple_reflows  # type: ignore


@pytest.fixture
def base_grammar():
    return DocumentGrammar(
        page_width=612.0,
        page_height=792.0,
        margin_top=54.0,
        margin_bottom=54.0,
        margin_left=54.0,
        margin_right=54.0,
        column_count=2,
        column_regions=[
            ColumnRegion(0, 54.0, 288.0, 234.0),
            ColumnRegion(1, 324.0, 558.0, 234.0),
        ],
        split_x=306.0,
        column_gap=36.0,
        body_fontname="Times-Roman",
        body_fontsize=10.0,
        body_line_height=12.0,
        paragraph_spacing=6.0,
        heading_styles={"h1": {"fontname": "Times-Bold", "fontsize": 12.0, "is_bold": True}},
    )


class TestParagraphPreservationAndWrapping:
    """Verify that logical paragraphs are preserved and can cross physical region boundaries."""

    def test_multi_paragraph_preserved_in_distribution(self, base_grammar):
        engine = ReflowEngine()
        # Region 0 is 200pt high (~16 lines), Region 1 is 200pt high (~16 lines)
        r0 = FlowRegion(page=1, column=0, bbox=BBox(54, 100, 288, 300), column_width=234.0, heading_bottom_y=100.0)
        r1 = FlowRegion(page=1, column=1, bbox=BBox(324, 100, 558, 300), column_width=234.0)

        para1 = "This is the first distinct paragraph. " * 8
        para2 = "This is the second distinct paragraph that begins here. " * 8
        full_text = f"{para1}\n\n{para2}"

        patches, rem = engine._distribute_text(full_text, [r0, r1], base_grammar)

        assert rem == ""
        assert len(patches) == 2
        # Verify that the text placed into r0 has paragraph 1, and r1 has the continuation/paragraph 2
        assert "first distinct paragraph" in patches[0].text_segment
        assert "second distinct paragraph" in (patches[0].text_segment + " " + patches[1].text_segment)

    def test_single_long_paragraph_crosses_region_boundary(self, base_grammar):
        engine = ReflowEngine()
        r0 = FlowRegion(page=1, column=0, bbox=BBox(54, 100, 288, 200), column_width=234.0)
        r1 = FlowRegion(page=1, column=1, bbox=BBox(324, 100, 558, 200), column_width=234.0)

        words = ["word" + str(i) for i in range(90)]
        long_para = " ".join(words)

        patches, rem = engine._distribute_text(long_para, [r0, r1], base_grammar)

        assert rem == ""
        assert len(patches) == 2
        assert len(patches[0].text_segment.split()) > 0
        assert len(patches[1].text_segment.split()) > 0
        # Recombined words must match original exactly
        recombined = patches[0].text_segment.split() + patches[1].text_segment.split()
        assert recombined == words


class TestSingleColumnAndTwoColumnReflow:
    """Test flow behavior across single-column and two-column geometries."""

    def test_single_column_shrink_and_overflow(self):
        grammar = DocumentGrammar(
            page_width=612.0,
            page_height=792.0,
            margin_top=54.0,
            margin_bottom=54.0,
            margin_left=54.0,
            margin_right=54.0,
            column_count=1,
            column_regions=[ColumnRegion(0, 54.0, 558.0, 504.0)],
            split_x=None,
            column_gap=0.0,
            body_fontname="Times-Roman",
            body_fontsize=10.0,
            body_line_height=12.0,
            paragraph_spacing=6.0,
            heading_styles={},
        )
        r0 = FlowRegion(page=1, column=0, bbox=BBox(54, 100, 558, 250), column_width=504.0)
        hb = TextBlock("Heading", BBox(54, 80, 558, 98), 1, 0, "Times-Bold", 12.0, True, True, 0, 14.0)
        cb = TextBlock("Original single column body text.", BBox(54, 100, 558, 250), 1, 0, "Times-Roman", 10.0, False, False, 1, 12.0)
        sec = Section("sec1", "Heading", 1, None, hb, [cb], [r0], True)
        fm = DocumentFlowMap(grammar, [sec], [hb, cb], [])

        engine = ReflowEngine()

        # 1. Fits easily
        res1 = engine.plan(sec, "Short replacement text.", fm)
        assert res1.can_apply is True
        assert res1.section_patches[0].operation == "replace"

        # 2. Impossible overflow
        res2 = engine.plan(sec, "Huge impossible overflow text. " * 200, fm)
        assert res2.can_apply is False
        assert len(res2.overflow_warnings) > 0


class TestTransactionalSafetyAndRollback:
    """Ensure PDF patcher behaves atomically without partial corruption or leaking zero-byte files."""

    def test_failed_patch_does_not_create_output_file(self, base_grammar):
        # Create a simple valid 1-page PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as orig_f:
            orig_pdf_path = orig_f.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out_f:
            out_pdf_path = out_f.name

        try:
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text((54, 100), "Hello world text")
            doc.save(orig_pdf_path)
            doc.close()

            # Create an intentionally failing reflow result (text too large for region)
            r0 = FlowRegion(page=1, column=0, bbox=BBox(54, 100, 288, 105), column_width=234.0)
            patch = SectionPatch(
                region=r0,
                text_segment="This is a massive replacement that will definitely not fit in a 5pt height region " * 20,
                operation="replace",
            )
            bad_reflow = ReflowResult(
                section_patches=[patch],
                downstream_shifts=[],
                overflow_warnings=[],
                delta_lines=10,
                delta_points=120.0,
                affected_pages=[1],
                unaffected_pages=[],
                can_apply=True,
            )

            report = apply_reflow(
                original_pdf_path=orig_pdf_path,
                reflow_result=bad_reflow,
                grammar=base_grammar,
                non_content=[],
                output_path=out_pdf_path,
            )

            assert report.success is False
            assert not os.path.exists(out_pdf_path), "Failed patch left behind a corrupt/partial output file!"
        finally:
            for p in [orig_pdf_path, out_pdf_path]:
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    def test_multi_section_edit_atomicity(self, base_grammar):
        """When multiple section edits are supplied, if one fails, none are applied."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as orig_f:
            orig_pdf_path = orig_f.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as out_f:
            out_pdf_path = out_f.name

        try:
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text((54, 100), "Section 1 text")
            page.insert_text((54, 400), "Section 2 text")
            doc.save(orig_pdf_path)
            doc.close()

            r1 = FlowRegion(page=1, column=0, bbox=BBox(54, 100, 288, 200), column_width=234.0)
            r2 = FlowRegion(page=1, column=0, bbox=BBox(54, 400, 288, 405), column_width=234.0)

            # Patch 1 succeeds
            res1 = ReflowResult(
                section_patches=[SectionPatch(r1, "Valid short text", "replace")],
                downstream_shifts=[], overflow_warnings=[], delta_lines=0, delta_points=0.0,
                affected_pages=[1], unaffected_pages=[], can_apply=True,
            )
            # Patch 2 overflows
            res2 = ReflowResult(
                section_patches=[SectionPatch(r2, "Excessive text overflowing 5pt box " * 30, "replace")],
                downstream_shifts=[], overflow_warnings=[], delta_lines=10, delta_points=120.0,
                affected_pages=[1], unaffected_pages=[], can_apply=True,
            )

            report = apply_multiple_reflows(
                original_pdf_path=orig_pdf_path,
                reflow_results=[res1, res2],
                grammar=base_grammar,
                non_content=[],
                output_path=out_pdf_path,
            )

            assert report.success is False
            assert not os.path.exists(out_pdf_path), "Multi-section failure must not leave partial output"
        finally:
            for p in [orig_pdf_path, out_pdf_path]:
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
