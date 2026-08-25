"""Tests for document-aware M7 semantic section detection."""

import pytest

from superdocs_template_inference.clustering.result import FamilyCluster
from superdocs_template_inference.models import (
    Document,
    DocumentProfile,
    ParagraphBlock,
    TableBlock,
)
from superdocs_template_inference.template_inference import TemplateInferer
from superdocs_template_inference.template_inference.sections_document_aware import (
    detect_semantic_sections_from_document,
    _detect_employee_information_table,
    _detect_first_day_table,
    _detect_orientation_table,
    merge_sections_preserving_headings,
)
from superdocs_template_inference.models import DetectedSection


def create_test_document(
    document_id: str,
    filename: str,
    blocks: list = None,
) -> Document:
    """Create a test Document with specified blocks."""
    if blocks is None:
        blocks = []

    return Document(
        document_id=document_id,
        filename=filename,
        file_type="docx",
        loaded_at="2026-01-01T00:00:00Z",
        blocks=blocks,
    )


def create_test_paragraph(text: str, is_heading: bool = False, heading_level: int | None = None) -> ParagraphBlock:
    """Create a test ParagraphBlock."""
    return ParagraphBlock(
        text=text,
        style_name="Heading 1" if is_heading else "Normal",
        is_heading=is_heading,
        heading_level=heading_level,
    )


def create_test_table(rows: list[list[str]]) -> TableBlock:
    """Create a test TableBlock."""
    return TableBlock(rows=rows)


class TestTableDetection:
    """Tests for table content analysis."""

    def test_detect_employee_information_table(self):
        """Detect tables with employee information keywords."""
        table = create_test_table([
            ["Employee ID", "Position", "Department"],
            ["E001", "Software Engineer", "Engineering"],
            ["E002", "Product Manager", "Product"],
        ])
        assert _detect_employee_information_table(table) is True

    def test_detect_first_day_table(self):
        """Detect tables with first-day information keywords."""
        table = create_test_table([
            ["Start Date", "Arrival Time", "Location"],
            ["2026-01-15", "09:00 AM", "Building A, Floor 2"],
        ])
        assert _detect_first_day_table(table) is True

    def test_detect_orientation_table(self):
        """Detect tables with orientation keywords."""
        table = create_test_table([
            ["Orientation", "Training", "Schedule"],
            ["Welcome Session", "HR Training", "Monday 10 AM"],
        ])
        assert _detect_orientation_table(table) is True

    def test_reject_unrelated_table(self):
        """Reject tables without semantic keywords."""
        table = create_test_table([
            ["Column A", "Column B"],
            ["Value 1", "Value 2"],
        ])
        assert _detect_employee_information_table(table) is False
        assert _detect_first_day_table(table) is False
        assert _detect_orientation_table(table) is False


class TestDocumentSemanticDetection:
    """Tests for document-aware semantic section detection."""

    def test_detect_company_header_from_document(self):
        """Detect company header from Document blocks."""
        document = create_test_document(
            "doc_001",
            "offer_001.docx",
            blocks=[
                create_test_paragraph("Tech Company Inc."),
                create_test_paragraph("123 Main Street"),
                create_test_paragraph("Phone: 555-0123 | Email: contact@tech.com"),
                create_test_paragraph("Welcome letter content..."),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect company header
        assert any(s.title == "company_header" for s in sections)

    def test_detect_employee_information_semantic_section(self):
        """Detect employee information section from table content."""
        document = create_test_document(
            "doc_002",
            "onboarding_002.docx",
            blocks=[
                create_test_paragraph("Welcome"),
                create_test_table([
                    ["Employee ID", "Position", "Department", "Manager"],
                    ["E001", "Engineer", "Engineering", "Bob Smith"],
                ]),
                create_test_paragraph("Your team is excited to have you!"),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect employee information section
        assert any(s.title == "employee_information" for s in sections)

    def test_detect_first_day_semantic_section(self):
        """Detect first-day section from table content."""
        document = create_test_document(
            "doc_003",
            "onboarding_003.docx",
            blocks=[
                create_test_paragraph("Welcome"),
                create_test_paragraph("YOUR FIRST DAY"),
                create_test_table([
                    ["Start Date", "Arrival Time", "Location", "Work Mode"],
                    ["Monday, Jan 15", "9:00 AM", "HQ, Floor 2", "Office"],
                ]),
                create_test_paragraph("Please check in at reception."),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect first-day section
        assert any(s.title == "first_day" for s in sections)

    def test_detect_orientation_semantic_section(self):
        """Detect orientation section from table content."""
        document = create_test_document(
            "doc_004",
            "onboarding_004.docx",
            blocks=[
                create_test_paragraph("Welcome"),
                create_test_table([
                    ["Orientation Session", "Trainer", "Time", "Location"],
                    ["Company Overview", "HR", "10:00 AM", "Conference Room"],
                    ["Onboarding Training", "IT", "2:00 PM", "Tech Lab"],
                ]),
                create_test_paragraph("End of orientation details"),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect orientation section
        assert any(s.title == "orientation" for s in sections)

    def test_detect_greeting_semantic_section(self):
        """Detect greeting section from paragraph content."""
        document = create_test_document(
            "doc_005",
            "offer_005.docx",
            blocks=[
                create_test_paragraph("Company Header"),
                create_test_paragraph("Dear John,"),
                create_test_paragraph("We are pleased to offer you a position..."),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect greeting section
        assert any(s.title == "greeting" for s in sections)

    def test_detect_closing_semantic_section(self):
        """Detect closing/signature section from document end."""
        document = create_test_document(
            "doc_006",
            "offer_006.docx",
            blocks=[
                create_test_paragraph("Position details and compensation..."),
                create_test_paragraph("Sincerely,"),
                create_test_paragraph("Jane Smith"),
                create_test_paragraph("CEO, Tech Company Inc."),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect closing section
        assert any(s.title == "closing_signature" for s in sections)

    def test_empty_document_produces_no_sections(self):
        """Empty document produces no semantic sections."""
        document = create_test_document("doc_007", "empty.docx", blocks=[])

        sections = detect_semantic_sections_from_document(document)

        assert len(sections) == 0

    def test_document_with_only_paragraphs_produces_limited_sections(self):
        """Document with only paragraphs detects only greeting/closing if present."""
        document = create_test_document(
            "doc_008",
            "minimal.docx",
            blocks=[
                create_test_paragraph("Hello"),
                create_test_paragraph("This is content"),
                create_test_paragraph("Best regards"),
            ],
        )

        sections = detect_semantic_sections_from_document(document)

        # Should detect greeting and closing
        titles = [s.title for s in sections]
        assert "greeting" in titles or "closing_signature" in titles


class TestBackwardCompatibility:
    """Tests for backward compatibility with profile-based M7."""

    def test_infer_without_documents_uses_profile_based_detection(self):
        """Calling infer() without documents_by_id uses profile-based detection."""
        from superdocs_template_inference.models import (
            ContentProfile,
            DocumentProfile,
            FormattingProfile,
            StructuralProfile,
        )

        inferer = TemplateInferer()

        # Create profile without documents
        profile = DocumentProfile(
            profile_id="profile_001",
            document_id="doc_001",
            filename="doc_001.docx",
            file_type="docx",
            structural=StructuralProfile(
                total_blocks=3,
                paragraph_count=2,
                heading_count=0,
                table_count=1,
                list_item_count=0,
                heading_levels={},
                max_heading_level=None,
                table_dimensions=[(2, 3)],
                avg_table_rows=None,
                avg_table_cols=None,
                block_type_sequence=["paragraph", "table", "paragraph"],
                paragraph_lengths=[50, 50],
                avg_paragraph_length=50.0,
                min_paragraph_length=50,
                max_paragraph_length=50,
                list_depth_max=None,
                ordered_list_count=0,
                unordered_list_count=0,
            ),
            content=ContentProfile(
                total_text_length=200,
                word_count=40,
                unique_words_count=30,
                heading_texts=[],
                vocabulary={"hello": 1, "welcome": 1},
                top_vocabulary=[("hello", 1), ("welcome", 1)],
            ),
            formatting=FormattingProfile(
                paragraph_styles={},
                heading_styles={},
                has_tables=True,
                has_lists=False,
                has_headings=False,
            ),
            sections=[],
            profiled_at="2026-01-01T00:00:00Z",
            profile_version="1.0",
        )

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=["doc_001"],
            document_filenames=["doc_001.docx"],
            confidence=0.9,
            cluster_size=1,
            pairwise_scores=[],
            pairwise_score_mean=1.0,
            pairwise_score_min=1.0,
            merge_evidence=[],
        )

        # Call infer() without documents_by_id (backward compatibility)
        result = inferer.infer(family_cluster, {"doc_001": profile})

        assert result.family_id == "family_001"
        assert result.document_ids == ["doc_001"]
        # Should still produce a result even without documents

    def test_infer_with_documents_enhances_detection(self):
        """Calling infer() with documents_by_id enables document-aware detection."""
        from superdocs_template_inference.models import (
            ContentProfile,
            DocumentProfile,
            FormattingProfile,
            StructuralProfile,
        )

        inferer = TemplateInferer()

        # Create document with semantic table
        document = create_test_document(
            "doc_002",
            "onboarding_002.docx",
            blocks=[
                create_test_paragraph("Welcome"),
                create_test_table([
                    ["Employee ID", "Position", "Department"],
                    ["E001", "Engineer", "Engineering"],
                ]),
                create_test_paragraph("Ready to start!"),
            ],
        )

        # Create matching profile
        profile = DocumentProfile(
            profile_id="profile_002",
            document_id="doc_002",
            filename="onboarding_002.docx",
            file_type="docx",
            structural=StructuralProfile(
                total_blocks=3,
                paragraph_count=2,
                heading_count=0,
                table_count=1,
                list_item_count=0,
                heading_levels={},
                max_heading_level=None,
                table_dimensions=[(2, 3)],
                avg_table_rows=None,
                avg_table_cols=None,
                block_type_sequence=["paragraph", "table", "paragraph"],
                paragraph_lengths=[50, 50],
                avg_paragraph_length=50.0,
                min_paragraph_length=50,
                max_paragraph_length=50,
                list_depth_max=None,
                ordered_list_count=0,
                unordered_list_count=0,
            ),
            content=ContentProfile(
                total_text_length=200,
                word_count=40,
                unique_words_count=30,
                heading_texts=["Welcome"],
                vocabulary={"employee": 1, "engineer": 1},
                top_vocabulary=[("employee", 1), ("engineer", 1)],
            ),
            formatting=FormattingProfile(
                paragraph_styles={},
                heading_styles={},
                has_tables=True,
                has_lists=False,
                has_headings=False,
            ),
            sections=[],
            profiled_at="2026-01-01T00:00:00Z",
            profile_version="1.0",
        )

        family_cluster = FamilyCluster(
            family_id="family_002",
            document_ids=["doc_002"],
            document_filenames=["onboarding_002.docx"],
            confidence=0.9,
            cluster_size=1,
            pairwise_scores=[],
            pairwise_score_mean=1.0,
            pairwise_score_min=1.0,
            merge_evidence=[],
        )

        # Call infer() WITH documents_by_id (document-aware detection)
        result = inferer.infer(
            family_cluster,
            {"doc_002": profile},
            {"doc_002": document},  # Pass documents for enhanced detection
        )

        assert result.family_id == "family_002"
        assert result.document_ids == ["doc_002"]
        # With document-aware detection, should have more semantic sections
        section_titles = [s.title_or_pattern for s in result.sections]
        assert any("employee" in title.lower() or "semantic" in title.lower()
                  for title in section_titles)


class TestSectionMerging:
    """Tests for merging document-detected sections with profile sections."""

    def test_preserve_heading_based_sections(self):
        """Heading-based sections are preserved when merging."""
        heading_section = DetectedSection(
            section_id="sec_0",
            start_block_idx=0,
            end_block_idx=2,
            title="Introduction",
            heading_level=1,
            block_count=3,
            paragraph_count=2,
            table_count=0,
            content_length=150,
            boundary_marker="heading",
        )

        document_section = DetectedSection(
            section_id="semantic_1",
            start_block_idx=3,
            end_block_idx=4,
            title="employee_information",
            heading_level=None,
            block_count=2,
            paragraph_count=0,
            table_count=1,
            content_length=50,
            boundary_marker="semantic_pattern",
        )

        merged = merge_sections_preserving_headings([heading_section], [document_section])

        # Both sections should be present
        assert len(merged) == 2
        assert any(s.boundary_marker == "heading" for s in merged)
        assert any(s.boundary_marker == "semantic_pattern" for s in merged)

    def test_avoid_overlapping_sections(self):
        """Overlapping sections are not duplicated."""
        profile_section = DetectedSection(
            section_id="sec_0",
            start_block_idx=0,
            end_block_idx=3,
            title="Overview",
            heading_level=1,
            block_count=4,
            paragraph_count=3,
            table_count=0,
            content_length=200,
            boundary_marker="heading",
        )

        # This document section overlaps with profile section
        overlapping_section = DetectedSection(
            section_id="semantic_1",
            start_block_idx=1,
            end_block_idx=2,
            title="nested_data",
            heading_level=None,
            block_count=2,
            paragraph_count=1,
            table_count=0,
            content_length=50,
            boundary_marker="semantic_pattern",
        )

        merged = merge_sections_preserving_headings([profile_section], [overlapping_section])

        # Overlapping document section should not be added
        assert len(merged) == 1
        assert merged[0].boundary_marker == "heading"

    def test_merge_non_overlapping_sections(self):
        """Non-overlapping sections are merged together."""
        profile_section = DetectedSection(
            section_id="sec_0",
            start_block_idx=0,
            end_block_idx=1,
            title="Header",
            heading_level=1,
            block_count=2,
            paragraph_count=1,
            table_count=0,
            content_length=100,
            boundary_marker="heading",
        )

        # This document section does not overlap
        non_overlapping_section = DetectedSection(
            section_id="semantic_1",
            start_block_idx=3,
            end_block_idx=4,
            title="details",
            heading_level=None,
            block_count=2,
            paragraph_count=1,
            table_count=0,
            content_length=50,
            boundary_marker="semantic_pattern",
        )

        merged = merge_sections_preserving_headings([profile_section], [non_overlapping_section])

        # Both sections should be present
        assert len(merged) == 2
        # They should be sorted by start index
        assert merged[0].start_block_idx <= merged[1].start_block_idx


class TestDeterministicDocumentDetection:
    """Tests for deterministic document-aware detection."""

    def test_repeated_detection_produces_identical_sections(self):
        """Repeated calls to detect_semantic_sections_from_document produce identical results."""
        document = create_test_document(
            "doc_001",
            "test_001.docx",
            blocks=[
                create_test_paragraph("Tech Company"),
                create_test_paragraph("Dear John,"),
                create_test_table([
                    ["Employee ID", "Position"],
                    ["E001", "Engineer"],
                ]),
                create_test_paragraph("Sincerely,"),
            ],
        )

        result1 = detect_semantic_sections_from_document(document)
        result2 = detect_semantic_sections_from_document(document)

        # Same titles in same order
        assert [s.title for s in result1] == [s.title for s in result2]
        # Same boundaries
        assert [(s.start_block_idx, s.end_block_idx) for s in result1] == [
            (s.start_block_idx, s.end_block_idx) for s in result2
        ]

    def test_document_content_drives_detection_not_filename(self):
        """Document content patterns drive semantic detection, not filename."""
        blocks = [
            create_test_paragraph("Company ABC"),
            create_test_table([
                ["Employee ID", "Name"],
                ["001", "John"],
            ]),
        ]

        doc_with_offer_name = create_test_document("doc_1", "offer_xyz.docx", blocks=blocks)
        doc_with_onboarding_name = create_test_document("doc_2", "onboarding_xyz.docx", blocks=blocks)

        result1 = detect_semantic_sections_from_document(doc_with_offer_name)
        result2 = detect_semantic_sections_from_document(doc_with_onboarding_name)

        # Both should detect the same semantic zones based on content, not filename
        titles1 = sorted([s.title for s in result1])
        titles2 = sorted([s.title for s in result2])
        assert titles1 == titles2
