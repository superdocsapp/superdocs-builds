"""Regression tests for conditional inference fix using section_groups."""

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
from superdocs_template_inference.template_inference.conditionals import infer_conditional_rules


def create_minimal_profile(
    document_id: str,
    filename: str,
    vocabulary: dict | None = None,
    sections_data: list[dict] | None = None,
) -> DocumentProfile:
    """Create a minimal DocumentProfile for testing."""
    structural = StructuralProfile(
        total_blocks=10,
        paragraph_count=5,
        heading_count=2,
        table_count=0,
        list_item_count=0,
        heading_levels={1: 2},
        max_heading_level=1,
        table_dimensions=[],
        avg_table_rows=None,
        avg_table_cols=None,
        block_type_sequence=["paragraph"] * 5,
        paragraph_lengths=[40] * 5,
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
        heading_texts=["Heading 1", "Heading 2"],
        vocabulary=vocabulary or {},
        top_vocabulary=list((vocabulary or {}).items())[:5],
    )

    formatting = FormattingProfile(
        paragraph_styles={},
        heading_styles={},
        has_tables=False,
        has_lists=False,
        has_headings=True,
    )

    sections = []
    if sections_data:
        for section_dict in sections_data:
            section = DetectedSection(
                section_id=section_dict.get("section_id", "sec_0"),
                start_block_idx=section_dict.get("start_block_idx", 0),
                end_block_idx=section_dict.get("end_block_idx", 5),
                title=section_dict.get("title", "Section"),
                heading_level=section_dict.get("heading_level", 1),
                block_count=5,
                paragraph_count=2,
                table_count=0,
                content_length=200,
                boundary_marker="heading",
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


class TestConditionalInferenceWithSectionGroups:
    """Regression tests for conditional inference fix using section_groups."""

    def test_section_groups_enables_conditional_detection(self):
        """Test that passing section_groups enables proper conditional detection."""
        # Create profiles: 2 with remote setup, 1 without
        profiles = [
            create_minimal_profile(
                "doc_with_remote_1",
                "doc1.docx",
                vocabulary={"remote": 3, "work": 2, "setup": 1, "engineering": 1},
                sections_data=[
                    {"section_id": "sec_main", "title": "Main Header"},
                    {"section_id": "sec_remote", "title": "Remote Work Setup"},
                ],
            ),
            create_minimal_profile(
                "doc_with_remote_2",
                "doc2.docx",
                vocabulary={"remote": 3, "work": 2, "setup": 1, "engineering": 1},
                sections_data=[
                    {"section_id": "sec_main", "title": "Main Header"},
                    {"section_id": "sec_remote_2", "title": "Remote Work Setup"},
                ],
            ),
            create_minimal_profile(
                "doc_without_remote",
                "doc3.docx",
                vocabulary={"office": 3, "work": 2, "setup": 0, "engineering": 1},
                sections_data=[
                    {"section_id": "sec_main", "title": "Main Header"},
                ],
            ),
        ]

        # Build section_groups mapping (normalized title -> list of DetectedSection objects)
        section_groups = {}
        for profile in profiles:
            for section in profile.sections:
                normalized = section.title.replace(" ", "_").lower() if section.title else ""
                if normalized not in section_groups:
                    section_groups[normalized] = []
                section_groups[normalized].append(section)

        # Test with section_groups - should find condition
        conditional_rules = infer_conditional_rules(
            profiles, ["remote work setup"], section_groups
        )

        assert "remote work setup" in conditional_rules, "Should find conditional rule when section_groups provided"
        rule = conditional_rules["remote work setup"]
        assert rule["condition"]["value"] is not None, "Should detect discriminative term"
        assert rule["confidence"] > 0.5, "Should have reasonable confidence"

    def test_backward_compatibility_without_section_groups(self):
        """Test that conditional inference still works without section_groups (backward compat)."""
        # Create profiles with raw sections (old behavior)
        profiles = [
            create_minimal_profile(
                "doc_1",
                "doc1.docx",
                vocabulary={"remote": 3, "work": 2},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_minimal_profile(
                "doc_2",
                "doc2.docx",
                vocabulary={"remote": 3, "work": 2},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_minimal_profile(
                "doc_3",
                "doc3.docx",
                vocabulary={"office": 3, "work": 2},
                sections_data=[],
            ),
        ]

        # Call without section_groups (None) - should use fallback logic
        conditional_rules = infer_conditional_rules(
            profiles, ["remote work setup"], None
        )

        # Should still work with backward-compatible matching
        assert "remote work setup" in conditional_rules, "Should work without section_groups"

    def test_section_name_normalization_with_groups(self):
        """Test that section name normalization works correctly with section_groups."""
        # Create profiles
        profiles = [
            create_minimal_profile(
                "doc_1",
                "doc1.docx",
                vocabulary={"engineering": 3, "setup": 1},
                sections_data=[{"title": "Technical Environment Setup"}],
            ),
            create_minimal_profile(
                "doc_2",
                "doc2.docx",
                vocabulary={"marketing": 3, "setup": 1},
                sections_data=[],
            ),
        ]

        # Build section_groups with normalized keys
        section_groups = {
            "technical_environment_setup": [s for p in profiles for s in p.sections if s.title == "Technical Environment Setup"],
        }

        # Test with spaces-form optional name (output form)
        conditional_rules = infer_conditional_rules(
            profiles, ["technical environment setup"], section_groups
        )

        assert "technical environment setup" in conditional_rules, "Should match output form name"

    def test_no_false_conditionals_for_unrelated_sections(self):
        """Test that unrelated optional sections don't get false conditionals."""
        # Create profiles where sections are unrelated to vocabulary patterns
        profiles = [
            create_minimal_profile(
                "doc_1",
                "doc1.docx",
                vocabulary={"content": 1, "text": 1},
                sections_data=[{"title": "Appendix"}],
            ),
            create_minimal_profile(
                "doc_2",
                "doc2.docx",
                vocabulary={"content": 1, "text": 1},
                sections_data=[],
            ),
        ]

        section_groups = {
            "appendix": [s for p in profiles for s in p.sections if s.title == "Appendix"],
        }

        # "appendix" has no discriminative vocabulary
        conditional_rules = infer_conditional_rules(
            profiles, ["appendix"], section_groups
        )

        # Might return an appendix rule with weak evidence, or none at all
        # But if it does, confidence should be low or missing
        if "appendix" in conditional_rules:
            assert conditional_rules["appendix"].get("confidence", 0.0) < 0.5

    def test_end_to_end_with_template_inferer(self):
        """Test that TemplateInferer properly passes section_groups to infer_conditional_rules."""
        # Create profiles
        profiles = [
            create_minimal_profile(
                "doc_1",
                "doc1.docx",
                vocabulary={"remote": 3, "flexible": 2},
                sections_data=[
                    {"title": "Employment Header"},
                    {"title": "Remote Work Setup"},
                ],
            ),
            create_minimal_profile(
                "doc_2",
                "doc2.docx",
                vocabulary={"office": 3, "onsite": 2},
                sections_data=[
                    {"title": "Employment Header"},
                ],
            ),
        ]

        family_cluster = FamilyCluster(
            family_id="test_family",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.85],
            pairwise_score_mean=0.85,
            pairwise_score_min=0.85,
            merge_evidence=[],
        )

        inferer = TemplateInferer()
        result = inferer.infer(family_cluster, {p.document_id: p for p in profiles})

        # Should have inferred at least one conditional rule
        assert len(result.conditional_rules) > 0, "Should infer at least one conditional rule"

        # Should have at least one CONDITIONAL section
        conditional_sections = [s for s in result.sections if s.inferred_type == "CONDITIONAL"]
        assert len(conditional_sections) > 0, "Should have at least one CONDITIONAL section"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
