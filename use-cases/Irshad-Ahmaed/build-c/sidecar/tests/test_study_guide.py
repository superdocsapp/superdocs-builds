"""PyTest unit tests for Build C Study-Guide Generator."""

import pytest
from build_c.guide_generator import (
    StudyGuideGenerator,
    StudyGuideRequest,
    ChatRefineRequest,
    normalize_math_delimiters,
)
from build_c.guide_exporter import StudyGuideExporter


def test_normalize_math_delimiters():
    raw = r"The field is \( \mathbf{E} \) and the wave equation is \[ \nabla^2 \mathbf{E} = 0 \]"
    normalized = normalize_math_delimiters(raw)
    assert r"$\mathbf{E}$" in normalized
    assert "$$\n\\nabla^2 \\mathbf{E} = 0\n$$" in normalized


def test_study_guide_generation_structure():
    gen = StudyGuideGenerator(api_key=None)
    req = StudyGuideRequest(
        subject="Electrodynamics",
        topic="Maxwell's Equations",
        target_exam="University STEM",
        raw_notes="del . E = rho/eps0, del x E = -dB/dt, del . B = 0",
        depth="detailed",
    )
    result = gen.generate_guide(req)
    assert result["success"] is True
    assert "session_id" in result
    md = result["guide_markdown"]
    assert "1. Quick Reference: Core Formulas & Key Terms" in md
    assert "2. Cornell Conceptual Breakdown" in md
    assert "3. Feynman Intuitive Explanation" in md
    assert "4. Active Recall & Practice Quiz" in md
    assert r"\nabla \cdot \mathbf{E}" in md


def test_multi_turn_chat_refinement():
    gen = StudyGuideGenerator(api_key=None)
    initial_md = "# Maxwell's Equations\n\n## 1. Quick Reference\nFormula table here."
    chat_req = ChatRefineRequest(
        session_id="test_sess_001",
        current_markdown=initial_md,
        instruction="Add wave speed derivation step-by-step",
    )
    refine_result = gen.refine_guide(chat_req)
    assert refine_result["success"] is True
    updated = refine_result["updated_markdown"]
    assert "Revision Note" in updated
    assert "wave speed derivation" in updated.lower()


def test_study_guide_pdf_export_and_stamping(tmp_path):
    exporter = StudyGuideExporter(api_key=None)
    md = """# Maxwell's Equations — Study Guide

## 1. Quick Reference
| Formula | Description |
| :--- | :--- |
| $$\\nabla \\cdot \\mathbf{E} = \\frac{\\rho}{\\varepsilon_0}$$ | Gauss Law |

## 2. Cornell Notes
Key concepts explained.
"""
    result = exporter.export_pdf(
        subject="Physics",
        topic="Maxwell Equations",
        guide_markdown=md,
    )
    assert result["success"] is True
    assert result["page_count"] >= 1
    assert "pdf_base64" in result
    assert result["pdf_base64"].startswith("JVBERi0")  # Standard PDF Magic Header in Base64
