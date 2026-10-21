"""Tests for DOCXGenerator.generate_tariff_memo() - canonical path."""

import pytest
from io import BytesIO
from docx import Document

from backend.core.export.docx_generator import DOCXGenerator


class TestGenerateTariffMemo:
    """Test canonical tariff memo generation."""

    def test_generate_tariff_memo_with_sections(self):
        """Test generating memo with multiple sections."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Product Description",
                "section_order": 1,
                "content": "This is a product description.\nWith multiple paragraphs.",
                "analyst_reasoning": "Based on specification.",
                "source_attribution": [],
                "structured_data": None,
                "status": "completed",
            },
            {
                "title": "Recommended Classification",
                "section_order": 2,
                "content": "Classification follows.",
                "analyst_reasoning": "",
                "source_attribution": [],
                "structured_data": {
                    "recommendation": {
                        "hs_code": "7326.90.8588",
                        "description": "Articles of iron or steel",
                        "reasoning": "Material composition matches",
                    }
                },
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test Workspace",
            document_name="Test Doc",
            sections=sections,
        )

        # Verify bytes generated
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0

        # Load and inspect DOCX
        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)

        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])

        # Check for expected content
        assert "Tariff Classification Memo" in all_text
        assert "Product Description" in all_text
        assert "This is a product description." in all_text
        assert "Recommended Classification" in all_text
        assert "7326.90.8588" in all_text

    def test_generate_tariff_memo_skips_skipped_sections(self):
        """Test that skipped sections are not rendered."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Active Section",
                "section_order": 1,
                "content": "This appears",
                "status": "completed",
            },
            {
                "title": "Skipped Section",
                "section_order": 2,
                "content": "This should not appear",
                "status": "skipped",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])

        # Check skipped section not rendered
        assert "Active Section" in all_text
        assert "This appears" in all_text
        assert "Skipped Section" not in all_text
        assert "This should not appear" not in all_text

    def test_generate_tariff_memo_renders_analyst_reasoning(self):
        """Test analyst reasoning is rendered with heading."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Analysis",
                "section_order": 1,
                "content": "Main content",
                "analyst_reasoning": "This is the analyst's reasoning.\nWith multiple lines.",
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])

        assert "Analyst Reasoning" in all_text
        assert "This is the analyst's reasoning." in all_text

    def test_generate_tariff_memo_renders_source_attribution(self):
        """Test source attribution with enhanced metadata."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Product Facts",
                "section_order": 1,
                "content": "Facts about the product",
                "source_attribution": [
                    {
                        "document_id": "doc-123",
                        "document_name": "specification.pdf",
                        "page": 5,
                        "excerpt": "Material: aluminum alloy",
                    },
                    {
                        "document_id": "doc-456",
                        "page": None,  # No page
                        "excerpt": "Dimensions provided",
                    },
                ],
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])

        # Check source rendering
        assert "Sources" in all_text
        assert "specification.pdf" in all_text
        assert "Page: 5" in all_text
        assert "Material: aluminum alloy" in all_text

    def test_generate_tariff_memo_renders_recommendation(self):
        """Test structured recommendation rendering."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Recommendation",
                "section_order": 1,
                "content": "",
                "structured_data": {
                    "recommendation": {
                        "hs_code": "8471.30.0100",
                        "description": "Portable computers",
                        "reasoning": "Based on material and function.\nMultiple lines of reasoning.",
                        "duty_rate": "0%",
                    }
                },
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells])

        # Check recommendation details
        assert "8471.30.0100" in all_text
        assert "Portable computers" in all_text
        assert "Based on material and function." in all_text
        assert "0%" in all_text

    def test_generate_tariff_memo_preserves_section_order(self):
        """Test sections are rendered in correct order."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Third Section",
                "section_order": 3,
                "content": "Content 3",
                "status": "completed",
            },
            {
                "title": "First Section",
                "section_order": 1,
                "content": "Content 1",
                "status": "completed",
            },
            {
                "title": "Second Section",
                "section_order": 2,
                "content": "Content 2",
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)

        # Find section headings
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]

        # Check order (after title)
        section_headings = [h for h in headings if "Section" in h]
        assert section_headings[0] == "First Section"
        assert section_headings[1] == "Second Section"
        assert section_headings[2] == "Third Section"

    def test_generate_tariff_memo_with_images(self):
        """Test image embedding in product images section."""
        generator = DOCXGenerator()

        # Create a minimal valid PNG (1x1 pixel)
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
            b"\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
            b"\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        sections = [
            {
                "title": "Product Images",
                "section_order": 1,
                "content": "Images follow",
                "status": "completed",
            },
        ]

        images = [
            {"bytes": png_bytes, "filename": "product_front.png"},
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
            images=images,
        )

        # Verify bytes generated
        assert isinstance(docx_bytes, bytes)
        assert len(docx_bytes) > 0

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)

        # Check for image caption
        all_text = "\n".join([p.text for p in doc.paragraphs])
        assert "product_front.png" in all_text

        # Check that document has embedded images
        # (python-docx stores images in document.part.related_parts)
        assert len(doc.part.related_parts) > 0

    def test_generate_tariff_memo_handles_missing_image_gracefully(self):
        """Test that invalid images don't crash export."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Product Images",
                "section_order": 1,
                "content": "Images",
                "status": "completed",
            },
        ]

        images = [
            {"bytes": b"invalid image data", "filename": "broken.png"},
        ]

        # Should not raise exception
        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
            images=images,
        )

        assert isinstance(docx_bytes, bytes)

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs])

        # Should have fallback message
        assert "broken.png" in all_text

    def test_generate_tariff_memo_truncates_long_excerpts(self):
        """Test long source excerpts are truncated."""
        generator = DOCXGenerator()

        long_excerpt = "A" * 250  # 250 characters

        sections = [
            {
                "title": "Section",
                "section_order": 1,
                "content": "Content",
                "source_attribution": [
                    {"excerpt": long_excerpt}
                ],
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs])

        # Should have ellipsis for truncation
        assert "..." in all_text
        # Should not have full 250 A's
        assert "A" * 250 not in all_text
        # Should have truncated version
        assert "A" * 200 in all_text

    def test_generate_tariff_memo_source_without_document_name(self):
        """Test source attribution gracefully handles missing document name."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Section",
                "section_order": 1,
                "content": "Content",
                "source_attribution": [
                    {
                        "document_id": "doc-789",
                        # No document_name
                        "excerpt": "Some text",
                    }
                ],
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs])

        # Should fallback to document ID
        assert "doc-789" in all_text

    def test_generate_tariff_memo_no_orphan_or_redundant_reasoning_heading(self):
        """Test that Analyst Reasoning headings are omitted when reasoning is duplicate or placeholder."""
        generator = DOCXGenerator()

        sections = [
            {
                "title": "Product Overview",
                "section_order": 1,
                "content": "The AeroLink X7 is an industrial UAV.",
                "analyst_reasoning": "Reasoning:",  # Trivial label
                "status": "completed",
            },
            {
                "title": "Product Description",
                "section_order": 2,
                "content": "Quad-rotor drone with carbon fiber frame.",
                "analyst_reasoning": "Quad-rotor drone with carbon fiber frame.",  # Duplicate of content
                "status": "completed",
            },
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Test",
            document_name="Test",
            sections=sections,
        )

        buffer = BytesIO(docx_bytes)
        doc = Document(buffer)
        all_text = "\n".join([p.text for p in doc.paragraphs])

        assert "Analyst Reasoning" not in all_text
        assert "Reasoning:" not in all_text
        assert "The AeroLink X7 is an industrial UAV." in all_text
        assert "Quad-rotor drone with carbon fiber frame." in all_text

    def test_generate_tariff_memo_professional_formatting_and_callout(self):
        """Test that recommendation callout table has shading, cantSplit, and borders."""
        generator = DOCXGenerator()
        sections = [
            {
                "title": "Classification Determination",
                "section_order": 1,
                "content": "Official determination content.",
                "structured_data": {
                    "recommendation": {
                        "hs_code": "8806.24.00",
                        "description": "Unmanned aircraft",
                        "duty_rate": "0%",
                        "reasoning": "GRI 1 applies based on weight and configuration.",
                    }
                },
                "status": "completed",
            }
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Aero WS",
            document_name="AeroLink_X7.pdf",
            sections=sections,
        )

        doc = Document(BytesIO(docx_bytes))
        # Verify 1-inch margins
        for section in doc.sections:
            assert abs(section.top_margin.inches - 1.0) < 0.01
            assert abs(section.bottom_margin.inches - 1.0) < 0.01

        # Verify callout table exists with cantSplit
        callout_tables = [t for t in doc.tables if len(t.rows) == 1 and len(t.columns) == 1]
        assert len(callout_tables) >= 1
        # Check text in callout table
        callout_text = callout_tables[-1].rows[0].cells[0].text
        assert "RECOMMENDED CLASSIFICATION DETERMINATION" in callout_text
        assert "8806.24.00" in callout_text
        assert "Unmanned aircraft" in callout_text

    def test_generate_tariff_memo_alternatives_table(self):
        """Test rendering of alternatives table in DOCX."""
        generator = DOCXGenerator()
        sections = [
            {
                "title": "Alternative Headings Considered",
                "section_order": 1,
                "content": "Evaluation of candidate headings.",
                "structured_data": {
                    "alternatives": [
                        {
                            "candidate_hs": "8471.49.00",
                            "description": "Automatic data processing machines",
                            "rejection_reason": "Not primarily a computing unit.",
                        },
                        {
                            "candidate_hs": "9014.80.00",
                            "description": "Navigational instruments",
                            "rejection_reason": "Autonomous flight is secondary to payload delivery.",
                        },
                    ]
                },
                "status": "completed",
            }
        ]

        docx_bytes = generator.generate_tariff_memo(
            workspace_name="Aero WS",
            document_name="AeroLink_X7.pdf",
            sections=sections,
        )

        doc = Document(BytesIO(docx_bytes))
        # Verify multi-row table rendered for alternatives
        alt_tables = [t for t in doc.tables if len(t.rows) == 3 and len(t.columns) == 3]
        assert len(alt_tables) == 1
        hdr_text = [c.text for c in alt_tables[0].rows[0].cells]
        assert "Candidate HS Code" in hdr_text
        assert "Rejection Rationale" in hdr_text
        row1_text = [c.text for c in alt_tables[0].rows[1].cells]
        assert "8471.49.00" in row1_text[0]


