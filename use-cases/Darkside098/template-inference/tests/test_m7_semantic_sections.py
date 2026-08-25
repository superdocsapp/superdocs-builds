"""Tests for M7: Semantic section detection."""

import pytest

from superdocs_template_inference.clustering.result import FamilyCluster
from superdocs_template_inference.models import (
    ContentProfile,
    DetectedSection,
    DocumentProfile,
    FormattingProfile,
    StructuralProfile,
)
from superdocs_template_inference.template_inference import TemplateInferer
from superdocs_template_inference.template_inference.sections import (
    detect_semantic_sections,
    augment_sections_with_semantic_names,
    _is_title_like,
    _is_greeting_like,
    _is_signature_block,
    _is_contact_info_block,
    _is_date_reference_block,
)


def create_test_profile(
    document_id: str,
    filename: str,
    heading_texts: list[str] | None = None,
    block_sequence: list[str] | None = None,
    table_dimensions: list[tuple[int, int]] | None = None,
    sections_data: list[dict] | None = None,
) -> DocumentProfile:
    """Create a test DocumentProfile with customizable block structure."""
    if heading_texts is None:
        heading_texts = []
    if block_sequence is None:
        block_sequence = ["paragraph"] * len(heading_texts)
    if table_dimensions is None:
        table_dimensions = []

    structural = StructuralProfile(
        total_blocks=len(block_sequence),
        paragraph_count=sum(1 for b in block_sequence if b == "paragraph"),
        heading_count=0,
        table_count=sum(1 for b in block_sequence if b == "table"),
        list_item_count=0,
        heading_levels={},
        max_heading_level=None,
        table_dimensions=table_dimensions,
        avg_table_rows=None,
        avg_table_cols=None,
        block_type_sequence=block_sequence,
        paragraph_lengths=[40] * sum(1 for b in block_sequence if b == "paragraph"),
        avg_paragraph_length=40.0,
        min_paragraph_length=20,
        max_paragraph_length=60,
        list_depth_max=None,
        ordered_list_count=0,
        unordered_list_count=0,
    )

    content = ContentProfile(
        total_text_length=500,
        word_count=100,
        unique_words_count=50,
        heading_texts=heading_texts,
        vocabulary={},
        top_vocabulary=[],
    )

    formatting = FormattingProfile(
        paragraph_styles={},
        heading_styles={},
        has_tables=len(table_dimensions) > 0,
        has_lists=False,
        has_headings=False,
    )

    sections = []
    if sections_data:
        for section_dict in sections_data:
            section = DetectedSection(
                section_id=section_dict.get("section_id", "sec_0"),
                start_block_idx=section_dict.get("start_block_idx", 0),
                end_block_idx=section_dict.get("end_block_idx", 5),
                title=section_dict.get("title", "Section"),
                heading_level=section_dict.get("heading_level", None),
                block_count=section_dict.get("block_count", 5),
                paragraph_count=section_dict.get("paragraph_count", 2),
                table_count=section_dict.get("table_count", 0),
                content_length=section_dict.get("content_length", 200),
                boundary_marker=section_dict.get("boundary_marker", "heading"),
            )
            sections.append(section)

    return DocumentProfile(
        profile_id=f"profile_{document_id}",
        document_id=document_id,
        filename=filename,
        file_type="docx",
        structural=structural,
        content=content,
        formatting=formatting,
        sections=sections,
        profiled_at="2026-01-01T00:00:00Z",
        profile_version="1.0",
    )


class TestTextPatternDetection:
    """Tests for text pattern detection helpers."""

    def test_is_title_like_uppercase(self):
        """Title-like detection recognizes uppercase text."""
        assert _is_title_like("EMPLOYEE ONBOARDING LETTER") is True
        assert _is_title_like("WELCOME")  is True
        assert _is_title_like("Remote Work Setup") is True

    def test_is_title_like_rejects_long_text(self):
        """Title-like detection rejects long text."""
        long_text = "This is a very long paragraph that goes on and on and should not be considered a title even if it has some uppercase words"
        assert _is_title_like(long_text) is False

    def test_is_greeting_like(self):
        """Greeting detection recognizes greeting patterns."""
        assert _is_greeting_like("Dear John") is True
        assert _is_greeting_like("Hello all") is True
        assert _is_greeting_like("Welcome to our company") is True
        assert _is_greeting_like("This is not a greeting") is False

    def test_is_signature_block(self):
        """Signature detection recognizes signature patterns."""
        assert _is_signature_block("Sincerely,") is True
        assert _is_signature_block("Warm regards") is True
        assert _is_signature_block("John Doe") is True
        assert _is_signature_block("CEO") is True

    def test_is_contact_info_block(self):
        """Contact info detection recognizes email/phone patterns."""
        assert _is_contact_info_block("john@example.com") is True
        assert _is_contact_info_block("555-123-4567") is True
        assert _is_contact_info_block("Phone: 555-987-6543") is True
        assert _is_contact_info_block("Website: www.example.com") is True

    def test_is_date_reference_block(self):
        """Date/reference detection recognizes date patterns."""
        assert _is_date_reference_block("Date: 01/15/2024") is True
        assert _is_date_reference_block("Reference: ABC-123") is True
        assert _is_date_reference_block("January 15, 2024") is True


class TestSemanticSectionDetection:
    """Tests for M7 semantic section detection."""

    def test_no_semantic_sections_with_empty_profile(self):
        """Empty profile produces no semantic sections."""
        profile = create_test_profile("doc_001", "doc_001.docx")

        sections = detect_semantic_sections(profile)

        assert sections == []

    def test_detects_company_header_with_early_table(self):
        """Company header zone is detected when table appears early."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Company Name", "123 Main St", "contact@example.com"],
            block_sequence=["paragraph", "paragraph", "table", "paragraph"],
            table_dimensions=[(3, 2)],
        )

        sections = detect_semantic_sections(profile)

        # Should detect header zone
        assert any(s.title == "company_header" for s in sections)

    def test_detects_greeting_block(self):
        """Greeting block is detected from greeting patterns."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Company Name", "Dear John", "Thank you for accepting"],
            block_sequence=["paragraph", "paragraph", "paragraph"],
        )

        sections = detect_semantic_sections(profile)

        # Should detect greeting zone
        assert any(s.title == "greeting" for s in sections)

    def test_detects_employee_information_table(self):
        """Employee information table zone is detected."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Employee Information", "John Doe", "Engineering"],
            block_sequence=["paragraph", "table", "paragraph"],
            table_dimensions=[(4, 3)],
        )

        sections = detect_semantic_sections(profile)

        # Should detect employee info zone
        assert any("employee" in s.title.lower() for s in sections)

    def test_detects_first_day_table(self):
        """First day information table is detected."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Start Date", "Arrival Time", "Work Mode", "Monday, January 15"],
            block_sequence=["paragraph", "table", "paragraph"],
            table_dimensions=[(4, 2)],
        )

        sections = detect_semantic_sections(profile)

        # Should detect first day zone
        assert any("first_day" in s.title.lower() for s in sections)

    def test_detects_closing_signature_block(self):
        """Closing/signature block is detected at document end."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Welcome message", "Thank you", "Sincerely", "Jane Smith"],
            block_sequence=["paragraph", "paragraph", "paragraph", "paragraph"],
        )

        sections = detect_semantic_sections(profile)

        # Should detect closing zone
        assert any("closing" in s.title.lower() or "signature" in s.title.lower() for s in sections)

    def test_semantic_sections_have_boundary_markers(self):
        """All semantic sections have semantic_pattern boundary marker."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Company", "Dear John", "Sincerely"],
            block_sequence=["paragraph", "paragraph", "paragraph"],
        )

        sections = detect_semantic_sections(profile)

        for section in sections:
            assert section.boundary_marker == "semantic_pattern"


class TestSemanticNameAugmentation:
    """Tests for augmenting sections with semantic names."""

    def test_augment_untitled_sections_with_greeting(self):
        """Untitled sections with greeting content get semantic names."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Dear John"],
        )

        sections = [
            DetectedSection(
                section_id="sec_0",
                start_block_idx=0,
                end_block_idx=1,
                title="untitled",
                heading_level=None,
                block_count=2,
                paragraph_count=1,
                table_count=0,
                content_length=100,
                boundary_marker="document_start",
            )
        ]

        augmented = augment_sections_with_semantic_names(sections, profile)

        # Untitled section should be renamed to greeting
        assert any(s.title == "greeting" for s in augmented)

    def test_preserve_named_sections(self):
        """Sections with meaningful names are preserved."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            heading_texts=["Introduction", "Content"],
        )

        sections = [
            DetectedSection(
                section_id="sec_0",
                start_block_idx=0,
                end_block_idx=1,
                title="introduction",
                heading_level=1,
                block_count=2,
                paragraph_count=1,
                table_count=0,
                content_length=100,
                boundary_marker="heading",
            )
        ]

        augmented = augment_sections_with_semantic_names(sections, profile)

        # Section name should be preserved
        assert augmented[0].title == "introduction"


class TestM7IntegrationWithInference:
    """Tests for M7 integration with template inference."""

    def test_onboarding_document_with_no_headings_produces_semantic_sections(self):
        """Onboarding document without heading styles can produce semantic sections."""
        inferer = TemplateInferer()

        # Create profiles of onboarding documents with no heading styles
        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"onboarding_{i:03d}.docx",
                heading_texts=[
                    "Company Name",
                    "EMPLOYEE ONBOARDING LETTER",
                    "Date",
                    "Dear Employee",
                    "Employee ID, Position, Department",
                    "WELCOME",
                    "Welcome content",
                    "YOUR ROLE",
                    "Role content",
                    "YOUR FIRST DAY",
                    "Start Date, Arrival Time",
                    "First day content",
                    "Sincerely",
                    "HR Manager",
                ],
                block_sequence=[
                    "paragraph", "paragraph", "paragraph", "paragraph",
                    "table", "paragraph", "paragraph", "paragraph",
                    "paragraph", "paragraph", "table", "paragraph",
                    "paragraph", "paragraph"
                ],
                table_dimensions=[(3, 2), (4, 2)],
            )
            for i in range(1, 3)
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.85],
            pairwise_score_mean=0.85,
            pairwise_score_min=0.85,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Should produce sections (from semantic detection)
        assert len(result.sections) > 0
        # Check for semantic zone names
        section_names = [s.title_or_pattern for s in result.sections]
        assert any("company" in name.lower() or "greeting" in name.lower() or "closing" in name.lower()
                  for name in section_names)

    def test_offer_document_with_headings_maintains_existing_sections(self):
        """Offer documents with heading styles keep their heading-based sections."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"offer_{i:03d}.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Position Details",
                        "heading_level": 1,
                    },
                    {
                        "section_id": "sec_1",
                        "title": "Compensation",
                        "heading_level": 1,
                    },
                ],
            )
            for i in range(1, 3)
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.85],
            pairwise_score_mean=0.85,
            pairwise_score_min=0.85,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Should preserve heading-based sections
        section_names = [s.title_or_pattern for s in result.sections]
        assert any("position" in name.lower() for name in section_names)
        assert any("compensation" in name.lower() for name in section_names)

    def test_deterministic_semantic_section_detection(self):
        """Semantic section detection is deterministic."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                heading_texts=["Company", "Dear John", "Sincerely"],
                block_sequence=["paragraph", "paragraph", "paragraph"],
            )
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

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

        result1 = inferer.infer(family_cluster, profiles_by_id)
        result2 = inferer.infer(family_cluster, profiles_by_id)

        # Results should be identical
        assert len(result1.sections) == len(result2.sections)
        assert [s.title_or_pattern for s in result1.sections] == [s.title_or_pattern for s in result2.sections]

    def test_filename_independent_semantic_detection(self):
        """Semantic section detection doesn't depend on filenames."""
        from superdocs_template_inference.template_inference.sections import (
            detect_semantic_sections,
        )

        # Same content, different filenames
        profile_offer = create_test_profile(
            "doc_001",
            "offer_letter.docx",
            heading_texts=["Dear John", "Sincerely"],
            block_sequence=["paragraph", "paragraph"],
        )

        profile_other = create_test_profile(
            "doc_002",
            "random_name.docx",
            heading_texts=["Dear John", "Sincerely"],
            block_sequence=["paragraph", "paragraph"],
        )

        # Directly test semantic detection to verify it's filename-independent
        sections_offer = detect_semantic_sections(profile_offer)
        sections_other = detect_semantic_sections(profile_other)

        # Both should detect the same semantic patterns
        assert len(sections_offer) == len(sections_other)
        assert [s.title for s in sections_offer] == [s.title for s in sections_other]
