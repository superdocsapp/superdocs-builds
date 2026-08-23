"""
Golden fixture regression tests using the real PilotMaster academic paper PDF.

Validates immutable-layout section reflow, cross-column paragraph flow,
heading protection, neighbouring content preservation, typography synchronization,
transactional PDF patching, and fidelity checking on VII. CONCLUSION.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'service'))

import tempfile
import pytest
import fitz

from pdf_analyzer import analyze_pdf  # type: ignore
from flow_mapper import build_flow_map  # type: ignore
from reflow_engine import ReflowEngine  # type: ignore
from pdf_patcher import apply_reflow  # type: ignore
from fidelity_checker import check_fidelity  # type: ignore


PILOTMASTER_PDF = os.path.join(
    os.path.dirname(__file__),
    "..",
    "demo",
    "PilotMaster - A Modular Retrieval Intelligence Platform for Retrieval Engineering, Observability, and Benchmarking.pdf",
)


@pytest.fixture(scope="module")
def pilotmaster_flow_map():
    assert os.path.exists(PILOTMASTER_PDF), f"PilotMaster PDF not found at {PILOTMASTER_PDF}"
    doc = analyze_pdf(PILOTMASTER_PDF)
    return build_flow_map(doc)


@pytest.fixture(scope="module")
def conclusion_section(pilotmaster_flow_map):
    conc = next((s for s in pilotmaster_flow_map.sections if "CONCLUSION" in s.title), None)
    assert conc is not None, "Section 'VII. CONCLUSION' not found in PilotMaster flow map"
    return conc


class TestGoldenPilotMasterConclusion:
    """Golden regression tests for PilotMaster Section VII. CONCLUSION."""

    def test_section_geometry_and_flow_regions(self, conclusion_section):
        """Verify that Section VII. CONCLUSION has 2 physical flow regions spanning Column 0 and Column 1."""
        regions = conclusion_section.flow_regions
        assert len(regions) == 2, f"Expected 2 flow regions for conclusion, got {len(regions)}"
        assert regions[0].page == 12 and regions[0].column == 0
        assert regions[1].page == 12 and regions[1].column == 1
        assert regions[0].bbox.height > 200.0
        assert regions[1].bbox.height > 150.0

    def test_shorter_replacement_succeeds(self, pilotmaster_flow_map, conclusion_section):
        """Shorter replacement (shrink case) should fit in Region 0 and mark Region 1 shrink_empty."""
        engine = ReflowEngine()
        short_text = (
            "This paper presented PilotMaster, a modular Retrieval Intelligence Platform that "
            "unifies document intelligence, retrieval observability, and experimental benchmarking "
            "within a shared retrieval engineering framework. The platform enables reproducible RAG workflows."
        )

        result = engine.plan(
            section=conclusion_section,
            replacement_text=short_text,
            flow_map=pilotmaster_flow_map,
        )

        assert result.can_apply is True
        assert len(result.section_patches) == 2
        # Region 0 has text, Region 1 is shrink_empty
        assert result.section_patches[0].operation == "replace"
        assert result.section_patches[1].operation == "shrink_empty"

    def test_realistic_rewrite_flows_across_columns_and_succeeds(self, pilotmaster_flow_map, conclusion_section):
        """A realistic 200-word rewrite flows from Column 0 to Column 1 and applies cleanly."""
        engine = ReflowEngine()
        rewrite_200 = (
            "This paper presented PilotMaster, a modular Retrieval Intelligence Platform that unifies "
            "document intelligence, retrieval observability, and experimental benchmarking within a shared retrieval "
            "engineering framework. By centralizing document ingestion, retrieval execution, evaluation, tracing, and "
            "benchmarking inside the reusable PilotCore framework, the platform enables multiple applications to operate "
            "over an identical retrieval pipeline while avoiding duplicated implementation. The resulting architecture "
            "provides consistent behavior across operational document question answering, execution observability, "
            "and controlled retrieval experimentation.\n\n"
            "The proposed platform demonstrates that retrieval engineering extends beyond response generation alone "
            "and requires comprehensive support for experimentation, pipeline observability, and systematic evaluation. "
            "By integrating DocPilot, TracePilot, and GaugePilot upon a common execution substrate, PilotMaster provides "
            "a unified environment for developing, diagnosing, and evaluating retrieval systems. The experimental results "
            "illustrate the value of execution tracing and comparative benchmarking across diverse retrieval configurations. "
            "Future extensions will investigate adaptive retrieval routing and expanded diagnostic capabilities."
        )

        result = engine.plan(
            section=conclusion_section,
            replacement_text=rewrite_200,
            flow_map=pilotmaster_flow_map,
        )

        assert result.can_apply is True, f"Rewrite 200 was rejected: {result.overflow_warnings}"
        assert len(result.section_patches) == 2
        # Both regions should have replacement content
        assert result.section_patches[0].operation == "replace"
        assert len(result.section_patches[0].text_segment.split()) > 80
        assert result.section_patches[1].operation == "replace"
        assert len(result.section_patches[1].text_segment.split()) > 0

    def test_impossible_overflow_is_safely_rejected(self, pilotmaster_flow_map, conclusion_section):
        """Excessively long text (>350 words) must be rejected under immutable layout policy."""
        engine = ReflowEngine()
        huge_text = (
            "This is an excessively long replacement that cannot possibly fit into the physical "
            "text regions allocated to the conclusion section. " * 30
        )

        result = engine.plan(
            section=conclusion_section,
            replacement_text=huge_text,
            flow_map=pilotmaster_flow_map,
        )

        assert result.can_apply is False
        assert len(result.overflow_warnings) > 0
        assert any("exceeds" in w.description.lower() or "overflow" in w.description.lower() for w in result.overflow_warnings)

    def test_failed_replacement_leaves_original_pdf_untouched(self, pilotmaster_flow_map, conclusion_section):
        """When an edit overflows or fails, the original PDF must remain untouched with no leaked temporary output."""
        engine = ReflowEngine()
        huge_text = "Overflow text that cannot fit inside this section. " * 80

        result = engine.plan(
            section=conclusion_section,
            replacement_text=huge_text,
            flow_map=pilotmaster_flow_map,
        )
        assert result.can_apply is False

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_out:
            out_pdf_path = tmp_out.name

        try:
            report = apply_reflow(
                original_pdf_path=PILOTMASTER_PDF,
                reflow_result=result,
                grammar=pilotmaster_flow_map.grammar,
                non_content=pilotmaster_flow_map.non_content,
                output_path=out_pdf_path,
            )
            assert report.success is False
            # Original file exists, is valid, and unmodified
            orig_doc = fitz.open(PILOTMASTER_PDF)
            assert len(orig_doc) == 12
            orig_doc.close()
            # Staging file is cleaned up
            assert not os.path.exists(out_pdf_path)
        finally:
            if os.path.exists(out_pdf_path):
                try:
                    os.unlink(out_pdf_path)
                except OSError:
                    pass

    def test_patch_pdf_fidelity_and_integrity(self, pilotmaster_flow_map, conclusion_section):
        """Applying the 200-word rewrite to the real PDF produces a pristine 12-page PDF."""
        engine = ReflowEngine()
        rewrite_200 = (
            "This paper presented PilotMaster, a unified Retrieval Intelligence Platform that combines "
            "document intelligence, observability, and experimental benchmarking within a shared framework. "
            "By centralizing ingestion, execution, evaluation, tracing, and benchmarking inside PilotCore, "
            "the platform enables multiple applications to operate over an identical retrieval pipeline "
            "while eliminating duplicated engineering effort. The resulting architecture ensures consistent "
            "behavior across question answering, execution observability, and controlled experimentation.\n\n"
            "The platform demonstrates that retrieval engineering requires end-to-end support for "
            "experimentation, evaluation, and diagnostics. Through DocPilot, TracePilot, and GaugePilot, "
            "PilotMaster delivers a comprehensive environment for optimizing RAG systems. Experimental "
            "results confirm the platform's ability to evaluate retrieval trade-offs reproducibly. "
            "Future extensions to indexing and retrieval strategies can be added to PilotCore without "
            "modifying the core architecture, maintaining consistency and modularity."
        )

        result = engine.plan(
            section=conclusion_section,
            replacement_text=rewrite_200,
            flow_map=pilotmaster_flow_map,
        )
        assert result.can_apply is True

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_out:
            out_pdf_path = tmp_out.name

        try:
            report = apply_reflow(
                original_pdf_path=PILOTMASTER_PDF,
                reflow_result=result,
                grammar=pilotmaster_flow_map.grammar,
                non_content=pilotmaster_flow_map.non_content,
                output_path=out_pdf_path,
            )

            assert report.success is True, f"apply_reflow failed: {[w.description for w in report.warnings]}"
            assert os.path.exists(out_pdf_path)
            assert os.path.getsize(out_pdf_path) > 1000

            # Verify PDF geometry and structure with PyMuPDF
            out_doc = fitz.open(out_pdf_path)
            assert len(out_doc) == 12, f"Expected 12 pages, got {len(out_doc)}"

            # Page dimensions unchanged (612 x 792)
            page12 = out_doc[11]
            assert abs(page12.rect.width - 612.0) < 1.0
            assert abs(page12.rect.height - 792.0) < 1.0

            page12_text = page12.get_text("text")

            # Check headings intact
            assert len(page12.search_for("VII. CONCLUSION")) > 0, "Heading VII. CONCLUSION was erased!"
            assert len(page12.search_for("VIII. PROJECT AVAILABILITY")) > 0, "Heading VIII. PROJECT AVAILABILITY was damaged!"
            assert len(page12.search_for("REFERENCES")) > 0, "REFERENCES heading was damaged!"

            # Check replacement text present (normalized whitespace)
            normalized_text = " ".join(page12_text.split())
            assert "PilotMaster, a unified Retrieval Intelligence Platform" in normalized_text
            out_doc.close()

            # Run FidelityChecker
            fidelity = check_fidelity(
                original_path=PILOTMASTER_PDF,
                modified_path=out_pdf_path,
                reflow_result=result,
                selected_section_names=["VII. CONCLUSION"],
                non_content=pilotmaster_flow_map.non_content,
            )

            assert fidelity.pass_overall is True, f"FidelityCheck failed: {fidelity.summary}"
            assert fidelity.page_count_changed is False
            assert fidelity.non_target_pages_changed == []
            assert fidelity.overflow_detected is False
            assert fidelity.figures_original == fidelity.figures_modified
            assert fidelity.tables_original == fidelity.tables_modified

        finally:
            if os.path.exists(out_pdf_path):
                try:
                    os.unlink(out_pdf_path)
                except OSError:
                    pass
