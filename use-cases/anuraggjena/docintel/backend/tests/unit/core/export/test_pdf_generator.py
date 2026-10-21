import io
import pytest
from pypdf import PdfReader

from backend.core.export.pdf_generator import PDFGenerator


def test_screenplay_pdf_generation_basic():
    generator = PDFGenerator()
    items = [
        {"element_index": 0, "element_type": "title", "formatted_text": "LAST CALL", "status": "approved"},
        {"element_index": 1, "element_type": "author", "formatted_text": "Written by A. Sharma", "status": "approved"},
        {"element_index": 2, "element_type": "scene_heading", "formatted_text": "INT. BAR - NIGHT", "status": "approved"},
        {"element_index": 3, "element_type": "action", "formatted_text": "A lonely patron sits at the counter.", "status": "approved"},
        {"element_index": 4, "element_type": "character", "formatted_text": "BARTENDER", "status": "approved"},
        {"element_index": 5, "element_type": "parenthetical", "formatted_text": "(wiping a glass)", "status": "approved"},
        {"element_index": 6, "element_type": "dialogue", "formatted_text": "What can I get you?", "status": "approved"},
        {"element_index": 7, "element_type": "transition", "formatted_text": "FADE OUT.", "status": "approved"},
        {"element_index": 8, "element_type": "end", "formatted_text": "THE END", "status": "approved"},
    ]

    pdf_bytes = generator.generate_screenplay_pdf(items, title="LAST CALL", workspace_name="Screenplay E2E Test")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    text = "".join(p.extract_text() for p in reader.pages)
    assert "LAST CALL" in text
    assert "Written by A. Sharma" in text
    assert "INT. BAR - NIGHT" in text
    assert "BARTENDER" in text
    assert "What can I get you?" in text
    assert "THE END" in text

    # Verify no generic document header / workspace branding is in the export
    assert "Formatted Screenplay" not in text
    assert "Screenplay E2E Test" not in text


def test_screenplay_pdf_rejected_status_uses_original_text():
    generator = PDFGenerator()
    items = [
        {
            "element_index": 0,
            "element_type": "scene_heading",
            "original_text": "int. cafe - day",
            "formatted_text": "INT. CAFE - DAY",
            "status": "rejected",
        },
        {
            "element_index": 1,
            "element_type": "dialogue",
            "original_text": "Hello world",
            "formatted_text": "HELLO WORLD",
            "status": "approved",
        },
    ]

    pdf_bytes = generator.generate_screenplay_pdf(items)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "int. cafe - day" in text
    assert "HELLO WORLD" in text


def test_tariff_memo_pdf_generation():
    generator = PDFGenerator()
    sections = [
        {
            "title": "1. Executive Summary",
            "section_order": 0,
            "content": "This memo analyzes the classification of solar inverters.",
            "analyst_reasoning": "Under GRI 1 and GRI 6, heading 8504 applies.",
            "source_attribution": [
                {"document_name": "Product_Spec.pdf", "page": 1, "excerpt": "Pure sine wave inverter"}
            ],
            "structured_data": {
                "recommendation": {
                    "hs_code": "8504.40.95",
                    "description": "Static converters for solar power",
                    "duty_rate": "0%",
                }
            },
        }
    ]

    pdf_bytes = generator.generate_tariff_memo(
        workspace_name="Tariff Test Workspace",
        document_name="Inverter_Spec.pdf",
        sections=sections,
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "Tariff Classification Memo" in text
    assert "Tariff Test Workspace" in text
    assert "Product_Spec.pdf" in text


def test_tariff_memo_pdf_no_orphan_reasoning():
    generator = PDFGenerator()
    sections = [
        {
            "title": "Product Overview",
            "section_order": 0,
            "content": "AeroLink X7 is an industrial drone.",
            "analyst_reasoning": "Reasoning:",  # Trivial label
            "source_attribution": [],
        },
        {
            "title": "Product Description",
            "section_order": 1,
            "content": "Quad-rotor drone with foldable arms.",
            "analyst_reasoning": "Quad-rotor drone with foldable arms.",  # Duplicate of content
            "source_attribution": [],
        },
    ]

    pdf_bytes = generator.generate_tariff_memo(
        workspace_name="Tariff Test Workspace",
        document_name="Drone.pdf",
        sections=sections,
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "Analysis & Reasoning" not in text
    assert "AeroLink X7 is an industrial drone." in text
    assert "Quad-rotor drone with foldable arms." in text


def test_tariff_report_pdf_generation():
    generator = PDFGenerator()
    claims = [
        {"content": "Duty rate is 2.5%", "status": "approved"},
        {"content": "Requires special license", "status": "rejected"},
    ]

    pdf_bytes = generator.generate_tariff_report(
        workspace_name="Tariff Test",
        document_name="Sample.pdf",
        claims=claims,
        generated_report="Final tariff analysis report content.",
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "Tariff Classification Report" in text
    assert "Final tariff analysis report content." in text
    assert "Duty rate is 2.5%" in text


def test_tariff_memo_pdf_callout_and_alternatives_table():
    generator = PDFGenerator()
    sections = [
        {
            "title": "1. Executive Summary",
            "section_order": 0,
            "content": "Executive overview of the drone classification.",
            "structured_data": {
                "recommendation": {
                    "hs_code": "8806.24.00",
                    "description": "Unmanned aircraft with max takeoff weight > 250g but <= 7kg",
                    "duty_rate": "Free",
                    "reasoning": "Classified under GRI 1 and GRI 6 in heading 8806.",
                },
                "alternatives": [
                    {
                        "candidate_hs": "8471.49.00",
                        "description": "Automatic data processing machines",
                        "rejection_reason": "Flight mechanics define the primary identity.",
                    }
                ],
            },
        }
    ]

    pdf_bytes = generator.generate_tariff_memo(
        workspace_name="Aero WS",
        document_name="AeroLink_X7.pdf",
        sections=sections,
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(p.extract_text() for p in reader.pages)
    assert "RECOMMENDED CLASSIFICATION DETERMINATION" in text
    assert "8806.24.00" in text
    assert "Alternative Classifications Table" in text
    assert "8471.49.00" in text
    assert "Page 1 of" in text

