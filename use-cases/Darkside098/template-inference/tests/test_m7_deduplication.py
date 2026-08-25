"""Regression tests for M7 semantic section deduplication."""

import pytest

from superdocs_template_inference.models import (
    DetectedSection,
    Document,
    DocumentProfile,
    ParagraphBlock,
    StructuralProfile,
    ContentProfile,
    FormattingProfile,
)
from superdocs_template_inference.template_inference.sections_document_aware import (
    deduplicate_semantic_sections,
    _canonical_title_for_dedup,
)
from superdocs_template_inference.template_inference.sections import (
    calculate_section_presence_frequency,
    align_sections,
)


def _create_test_profile(document_id: str, sections=None) -> DocumentProfile:
    """Helper to create a minimal DocumentProfile for testing."""
    if sections is None:
        sections = []

    return DocumentProfile(
        profile_id=f"profile_{document_id}",
        document_id=document_id,
        filename=f"{document_id}.docx",
        file_type="docx",
        structural=StructuralProfile(
            total_blocks=100,
            paragraph_count=50,
            heading_count=0,
            table_count=1,
            list_item_count=0,
            heading_levels={},
            max_heading_level=None,
            table_dimensions=[(2, 3)],
            avg_table_rows=None,
            avg_table_cols=None,
            block_type_sequence=["paragraph"] * 50 + ["table"] + ["paragraph"] * 50,
            paragraph_lengths=[100] * 50,
            avg_paragraph_length=100.0,
            min_paragraph_length=50,
            max_paragraph_length=150,
            list_depth_max=None,
            ordered_list_count=0,
            unordered_list_count=0,
        ),
        content=ContentProfile(
            total_text_length=5000,
            word_count=1000,
            unique_words_count=500,
            heading_texts=[],
            vocabulary={},
            top_vocabulary=[],
        ),
        formatting=FormattingProfile(
            paragraph_styles={},
            heading_styles={},
            has_tables=True,
            has_lists=False,
            has_headings=False,
        ),
        sections=sections,
        profiled_at="2026-01-01T00:00:00Z",
        profile_version="1.0",
    )


def test_canonical_title_normalizes_aliases():
    """Test that semantic aliases are mapped to canonical forms."""
    assert _canonical_title_for_dedup("first_day") == "first_day"
    assert _canonical_title_for_dedup("your_first_day") == "first_day"
    assert _canonical_title_for_dedup("Your First Day") == "first_day"
    assert _canonical_title_for_dedup("welcome") == "welcome"
    assert _canonical_title_for_dedup("welcome aboard") == "welcome"
    assert _canonical_title_for_dedup("orientation") == "orientation"


def test_canonical_title_empty_and_none():
    """Test canonical title with empty/None inputs."""
    assert _canonical_title_for_dedup(None) == ""
    assert _canonical_title_for_dedup("") == ""
    assert _canonical_title_for_dedup("   ") == ""


def test_deduplicate_overlapping_sections_same_title():
    """Test A: Deduplicate sections with same title and overlapping ranges."""
    section1 = DetectedSection(
        section_id="sec1",
        start_block_idx=5,
        end_block_idx=10,
        title="first_day",
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    section2 = DetectedSection(
        section_id="sec2",
        start_block_idx=7,
        end_block_idx=12,
        title="first_day",
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    sections = [section1, section2]
    deduplicated = deduplicate_semantic_sections(sections)

    # Should have only one section covering the full range
    assert len(deduplicated) == 1
    assert deduplicated[0].start_block_idx == 5
    assert deduplicated[0].end_block_idx == 12
    assert deduplicated[0].title == "first_day"


def test_deduplicate_preserves_separate_sections():
    """Test B: Ensure genuinely separate sections are NOT incorrectly collapsed."""
    section1 = DetectedSection(
        section_id="sec1",
        start_block_idx=5,
        end_block_idx=10,
        title="first_day",
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    section2 = DetectedSection(
        section_id="sec2",
        start_block_idx=20,
        end_block_idx=25,
        title="first_day",
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    sections = [section1, section2]
    deduplicated = deduplicate_semantic_sections(sections)

    # Should have two separate sections since they don't overlap
    assert len(deduplicated) == 2
    assert deduplicated[0].start_block_idx == 5
    assert deduplicated[0].end_block_idx == 10
    assert deduplicated[1].start_block_idx == 20
    assert deduplicated[1].end_block_idx == 25


def test_deduplicate_with_semantic_aliases():
    """Test deduplication works with semantic aliases."""
    section1 = DetectedSection(
        section_id="sec1",
        start_block_idx=5,
        end_block_idx=10,
        title="first_day",
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    section2 = DetectedSection(
        section_id="sec2",
        start_block_idx=7,
        end_block_idx=12,
        title="your_first_day",  # Alias for first_day
        heading_level=None,
        block_count=6,
        paragraph_count=3,
        table_count=1,
        content_length=150,
        boundary_marker="semantic_pattern",
    )

    sections = [section1, section2]
    deduplicated = deduplicate_semantic_sections(sections)

    # Should be merged since they're semantic aliases
    assert len(deduplicated) == 1
    assert deduplicated[0].start_block_idx == 5
    assert deduplicated[0].end_block_idx == 12


def test_deduplicate_maintains_ordering():
    """Test C: Deduplicated sections remain sorted by start_block_idx."""
    sections = [
        DetectedSection(
            section_id="sec1",
            start_block_idx=20,
            end_block_idx=25,
            title="orientation",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=1,
            content_length=150,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec2",
            start_block_idx=5,
            end_block_idx=10,
            title="welcome",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=1,
            content_length=150,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec3",
            start_block_idx=15,
            end_block_idx=18,
            title="role_and_department",
            heading_level=None,
            block_count=4,
            paragraph_count=2,
            table_count=0,
            content_length=100,
            boundary_marker="semantic_pattern",
        ),
    ]

    deduplicated = deduplicate_semantic_sections(sections)

    # Should be sorted and no overlaps
    assert len(deduplicated) == 3
    assert deduplicated[0].start_block_idx == 5
    assert deduplicated[1].start_block_idx == 15
    assert deduplicated[2].start_block_idx == 20


def test_deduplicate_no_overlaps():
    """Test D: Sections do not overlap after merging."""
    # Sections with various overlaps
    sections = [
        DetectedSection(
            section_id="sec1",
            start_block_idx=5,
            end_block_idx=15,
            title="first_day",
            heading_level=None,
            block_count=11,
            paragraph_count=5,
            table_count=1,
            content_length=300,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec2",
            start_block_idx=10,
            end_block_idx=20,
            title="your_first_day",  # Overlaps with first_day
            heading_level=None,
            block_count=11,
            paragraph_count=5,
            table_count=1,
            content_length=300,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec3",
            start_block_idx=30,
            end_block_idx=35,
            title="orientation",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=1,
            content_length=150,
            boundary_marker="semantic_pattern",
        ),
    ]

    deduplicated = deduplicate_semantic_sections(sections)

    # Should be 2 sections after merging first two
    assert len(deduplicated) == 2

    # Check no overlaps
    for i in range(len(deduplicated) - 1):
        assert deduplicated[i].end_block_idx < deduplicated[i + 1].start_block_idx


def test_frequency_single_document_all_profiles():
    """Test E: Section appearing once in each of 12 documents has frequency 1.0."""
    sections = [
        DetectedSection(
            section_id=f"sec{i}",
            start_block_idx=0,
            end_block_idx=10,
            title="first_day",
            heading_level=None,
            block_count=11,
            paragraph_count=5,
            table_count=1,
            content_length=200,
            boundary_marker="semantic_pattern",
        )
        for i in range(12)
    ]

    # Create profiles with the sections
    profiles = [
        _create_test_profile(f"doc{i:03d}", sections=[sections[i]])
        for i in range(12)
    ]

    section_groups = align_sections(profiles)
    frequency = calculate_section_presence_frequency("first_day", profiles, section_groups)

    # Should be exactly 1.0
    assert frequency == 1.0
    assert 0.0 <= frequency <= 1.0


def test_frequency_partial_presence():
    """Test F: Section appearing in 5 of 12 documents has frequency 5/12."""
    sections_with_first_day = [
        DetectedSection(
            section_id=f"sec{i}",
            start_block_idx=0,
            end_block_idx=10,
            title="first_day",
            heading_level=None,
            block_count=11,
            paragraph_count=5,
            table_count=1,
            content_length=200,
            boundary_marker="semantic_pattern",
        )
        for i in range(5)
    ]

    profiles = []

    # 5 profiles with first_day
    for i in range(5):
        profiles.append(
            _create_test_profile(f"doc{i:03d}", sections=[sections_with_first_day[i]])
        )

    # 7 profiles without first_day
    for i in range(5, 12):
        profiles.append(
            _create_test_profile(f"doc{i:03d}", sections=[])
        )

    section_groups = align_sections(profiles)
    frequency = calculate_section_presence_frequency("first_day", profiles, section_groups)

    # Should be approximately 5/12
    expected = 5 / 12
    assert abs(frequency - expected) < 0.01
    assert 0.0 <= frequency <= 1.0


def test_frequency_never_exceeds_one():
    """Test that frequency is always clamped to [0.0, 1.0]."""
    # Create a scenario where deduplication might not be perfect
    profile = _create_test_profile(
        "doc001",
        sections=[
            DetectedSection(
                section_id="sec1",
                start_block_idx=0,
                end_block_idx=10,
                title="first_day",
                heading_level=None,
                block_count=11,
                paragraph_count=5,
                table_count=1,
                content_length=200,
                boundary_marker="semantic_pattern",
            ),
            # Duplicate (this shouldn't happen after deduplication, but test clamping anyway)
            DetectedSection(
                section_id="sec2",
                start_block_idx=5,
                end_block_idx=12,
                title="first_day",
                heading_level=None,
                block_count=8,
                paragraph_count=4,
                table_count=1,
                content_length=180,
                boundary_marker="semantic_pattern",
            ),
        ]
    )

    profiles = [profile]
    section_groups = align_sections(profiles)
    frequency = calculate_section_presence_frequency("first_day", profiles, section_groups)

    # Should be clamped to 1.0 even if there are duplicates
    assert 0.0 <= frequency <= 1.0
    # Note: The frequency might be 1.0 due to clamping or deduplication


def test_empty_sections():
    """Test deduplication with empty section list."""
    deduplicated = deduplicate_semantic_sections([])
    assert deduplicated == []


def test_single_section():
    """Test deduplication with a single section."""
    section = DetectedSection(
        section_id="sec1",
        start_block_idx=0,
        end_block_idx=10,
        title="first_day",
        heading_level=None,
        block_count=11,
        paragraph_count=5,
        table_count=1,
        content_length=200,
        boundary_marker="semantic_pattern",
    )

    deduplicated = deduplicate_semantic_sections([section])

    assert len(deduplicated) == 1
    assert deduplicated[0] == section


def test_non_overlapping_sections():
    """Test that non-overlapping sections with different titles are preserved."""
    sections = [
        DetectedSection(
            section_id="sec1",
            start_block_idx=0,
            end_block_idx=5,
            title="welcome",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=0,
            content_length=100,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec2",
            start_block_idx=10,
            end_block_idx=15,
            title="role_and_department",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=0,
            content_length=100,
            boundary_marker="semantic_pattern",
        ),
        DetectedSection(
            section_id="sec3",
            start_block_idx=20,
            end_block_idx=25,
            title="first_day",
            heading_level=None,
            block_count=6,
            paragraph_count=3,
            table_count=0,
            content_length=100,
            boundary_marker="semantic_pattern",
        ),
    ]

    deduplicated = deduplicate_semantic_sections(sections)

    # All three should remain separate
    assert len(deduplicated) == 3
    for orig, dedup in zip(sections, deduplicated):
        assert dedup.start_block_idx == orig.start_block_idx
        assert dedup.end_block_idx == orig.end_block_idx
