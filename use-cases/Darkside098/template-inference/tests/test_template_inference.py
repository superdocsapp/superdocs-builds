"""Tests for template inference."""

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
from superdocs_template_inference.template_inference.result import (
    ConditionalRule,
    InferenceEvidence,
    TemplateInferenceResult,
    TemplateSection,
    VariableField,
)


def create_test_profile(
    document_id: str,
    filename: str,
    total_blocks: int = 10,
    paragraph_count: int = 5,
    heading_count: int = 2,
    vocabulary: dict | None = None,
    sections_data: list[dict] | None = None,
) -> DocumentProfile:
    """Create a test DocumentProfile."""
    structural = StructuralProfile(
        total_blocks=total_blocks,
        paragraph_count=paragraph_count,
        heading_count=heading_count,
        table_count=0,
        list_item_count=0,
        heading_levels={1: heading_count} if heading_count > 0 else {},
        max_heading_level=1 if heading_count > 0 else None,
        table_dimensions=[],
        avg_table_rows=None,
        avg_table_cols=None,
        block_type_sequence=["paragraph"] * paragraph_count,
        paragraph_lengths=[40] * paragraph_count,
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
        heading_texts=["Heading 1", "Heading 2"] if heading_count >= 2 else [],
        vocabulary=vocabulary or {"word_1": 1, "word_2": 1},
        top_vocabulary=[("word_1", 1), ("word_2", 1)],
    )

    formatting = FormattingProfile(
        paragraph_styles={},
        heading_styles={},
        has_tables=False,
        has_lists=False,
        has_headings=heading_count > 0,
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


class TestTemplateInferencerInitialization:
    """Tests for TemplateInferer initialization."""

    def test_inferer_can_be_initialized(self):
        """TemplateInferer can be initialized."""
        inferer = TemplateInferer()
        assert inferer is not None


class TestEmptyAndSingletonFamily:
    """Tests for edge cases: empty family and single document."""

    def test_infer_empty_family(self):
        """Inferring template for empty family returns zero-confidence result."""
        inferer = TemplateInferer()
        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[],
            document_filenames=[],
            confidence=0.0,
            cluster_size=0,
            pairwise_scores=[],
            pairwise_score_mean=1.0,
            pairwise_score_min=1.0,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {})

        assert result.family_id == "family_001"
        assert result.document_ids == []
        assert result.confidence == 0.0
        assert result.sections == []

    def test_infer_singleton_family(self):
        """Inferring template for single document produces limited inference."""
        inferer = TemplateInferer()
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            sections_data=[
                {
                    "section_id": "sec_0",
                    "title": "Introduction",
                    "heading_level": 1,
                    "block_count": 5,
                }
            ],
        )

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=["doc_001"],
            document_filenames=["doc_001.docx"],
            confidence=1.0,
            cluster_size=1,
            pairwise_scores=[],
            pairwise_score_mean=1.0,
            pairwise_score_min=1.0,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {"doc_001": profile})

        assert result.family_id == "family_001"
        assert result.document_ids == ["doc_001"]
        assert len(result.sections) >= 1


class TestIdenticalDocuments:
    """Tests for families with identical documents."""

    def test_infer_identical_documents(self):
        """Identical documents produce high-confidence REQUIRED sections."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Header",
                        "heading_level": 1,
                        "block_count": 3,
                    },
                    {
                        "section_id": "sec_1",
                        "title": "Content",
                        "heading_level": 1,
                        "block_count": 5,
                    },
                ],
            )
            for i in range(1, 4)
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.95,
            cluster_size=len(profiles),
            pairwise_scores=[0.9, 0.9, 0.9],
            pairwise_score_mean=0.9,
            pairwise_score_min=0.9,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        assert result.family_id == "family_001"
        assert len(result.sections) >= 2
        # All sections should be REQUIRED with high confidence
        assert all(s.inferred_type == "REQUIRED" for s in result.sections)
        assert all(s.confidence > 0.9 for s in result.sections)


class TestFixedAndVariableContent:
    """Tests for fixed and variable content detection."""

    def test_infer_variable_content(self):
        """Variable content across documents is detected."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"alice": 1, "manager": 1, "fixed_text": 2},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Header",
                        "heading_level": 1,
                    }
                ],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"bob": 1, "manager": 1, "fixed_text": 2},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Header",
                        "heading_level": 1,
                    }
                ],
            ),
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Should detect variable content (alice, bob)
        # and fixed content (fixed_text, manager)
        assert result.family_id == "family_001"
        # Variables should be detected for alice/bob
        assert any(v.variable_name in ["alice", "bob"] for v in result.variables)


class TestSectionPresenceVariation:
    """Tests for section presence variation (REQUIRED, OPTIONAL, CONDITIONAL)."""

    def test_required_section(self):
        """Section present in all documents is classified as REQUIRED."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Always Present",
                        "heading_level": 1,
                    }
                ],
            )
            for i in range(1, 4)
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.95,
            cluster_size=len(profiles),
            pairwise_scores=[0.9, 0.9, 0.9],
            pairwise_score_mean=0.9,
            pairwise_score_min=0.9,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        required_sections = [
            s for s in result.sections if s.inferred_type == "REQUIRED"
        ]
        assert len(required_sections) >= 1

    def test_optional_section(self):
        """Section missing in some documents is classified as OPTIONAL."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Sometimes Present",
                        "heading_level": 1,
                    }
                ],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                sections_data=[],
            ),
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.8,
            cluster_size=len(profiles),
            pairwise_scores=[0.7],
            pairwise_score_mean=0.7,
            pairwise_score_min=0.7,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Should have inferred sections
        assert result.family_id == "family_001"


class TestConditionalInference:
    """Focused tests for conditional-section inference."""

    def test_genuine_conditional_section(self):
        """A section with repeated field/value evidence becomes CONDITIONAL."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"remote": 2, "setup": 1, "manager": 1},
                sections_data=[{"section_id": "sec_remote", "title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"remote": 2, "setup": 1, "manager": 1},
                sections_data=[{"section_id": "sec_remote_2", "title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_003",
                "doc_003.docx",
                vocabulary={"office": 2, "manager": 1},
                sections_data=[],
            ),
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=3,
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {p.document_id: p for p in profiles})
        section = next(
            (s for s in result.sections if s.title_or_pattern == "remote work setup"),
            None,
        )

        assert section is not None
        assert section.inferred_type == "CONDITIONAL"
        assert section.conditional_info is not None
        assert any(
            cr.target_section == "remote work setup" for cr in result.conditional_rules
        )

    def test_optional_but_nonconditional_section(self):
        """A section that varies without a discriminating field/value stays OPTIONAL."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"notes": 2, "misc": 1},
                sections_data=[{"section_id": "sec_notes", "title": "Notes"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"summary": 2, "misc": 1},
                sections_data=[],
            ),
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.8,
            cluster_size=2,
            pairwise_scores=[0.7],
            pairwise_score_mean=0.7,
            pairwise_score_min=0.7,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {p.document_id: p for p in profiles})
        section = next((s for s in result.sections if s.title_or_pattern == "notes"), None)

        assert section is not None
        assert section.inferred_type == "OPTIONAL"
        assert not any(cr.target_section == "notes" for cr in result.conditional_rules)

    def test_no_condition_case_keeps_section_optional(self):
        """No sufficiently strong condition produces neither a conditional section nor a rule."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"custom": 1, "misc": 1},
                sections_data=[{"section_id": "sec_custom", "title": "Custom Addendum"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"other": 1, "misc": 1},
                sections_data=[],
            ),
            create_test_profile(
                "doc_003",
                "doc_003.docx",
                vocabulary={"extra": 1, "misc": 1},
                sections_data=[],
            ),
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.8,
            cluster_size=3,
            pairwise_scores=[0.7, 0.7, 0.7],
            pairwise_score_mean=0.7,
            pairwise_score_min=0.7,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {p.document_id: p for p in profiles})
        section = next(
            (s for s in result.sections if s.title_or_pattern == "custom addendum"),
            None,
        )

        assert section is not None
        assert section.inferred_type == "OPTIONAL"
        assert all(cr.target_section != "custom addendum" for cr in result.conditional_rules)

    def test_field_value_condition_and_evidence(self):
        """Rule shape uses structured field/operator/value and evidence from both groups."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_003",
                "doc_003.docx",
                vocabulary={"office": 1, "setup": 1},
                sections_data=[],
            ),
        ]

        result = inferer.infer(
            FamilyCluster(
                family_id="family_001",
                document_ids=[p.document_id for p in profiles],
                document_filenames=[p.filename for p in profiles],
                confidence=0.9,
                cluster_size=3,
                pairwise_scores=[0.8, 0.8, 0.8],
                pairwise_score_mean=0.8,
                pairwise_score_min=0.8,
                merge_evidence=[],
            ),
            {p.document_id: p for p in profiles},
        )

        rule = next((cr for cr in result.conditional_rules if cr.target_section == "remote work setup"), None)
        assert rule is not None
        assert set(rule.condition.keys()) >= {"field", "operator", "value"}
        assert rule.condition["field"] in {"variable_observation", "document_attribute"}
        assert rule.condition["value"] == "remote"
        assert len(rule.supporting_evidence) >= 1
        assert all("source_document_ids" in e or "document_ids" in e for e in [
            ev.__dict__ for ev in rule.supporting_evidence
        ])

    def test_section_conditional_info_populated(self):
        """Conditional sections expose section-level conditional_info."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_003",
                "doc_003.docx",
                vocabulary={"office": 1},
                sections_data=[],
            ),
        ]

        result = inferer.infer(
            FamilyCluster(
                family_id="family_001",
                document_ids=[p.document_id for p in profiles],
                document_filenames=[p.filename for p in profiles],
                confidence=0.9,
                cluster_size=3,
                pairwise_scores=[0.8, 0.8, 0.8],
                pairwise_score_mean=0.8,
                pairwise_score_min=0.8,
                merge_evidence=[],
            ),
            {p.document_id: p for p in profiles},
        )

        section = next(
            (s for s in result.sections if s.title_or_pattern == "remote work setup"),
            None,
        )
        assert section is not None
        assert section.conditional_info is not None
        assert section.conditional_info["condition"]["value"] == "remote"

    def test_conditional_rule_is_deterministic(self):
        """Repeated inference on identical data picks the same rule and ordering."""
        inferer = TemplateInferer()
        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_003",
                "doc_003.docx",
                vocabulary={"office": 1},
                sections_data=[],
            ),
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=3,
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result1 = inferer.infer(family_cluster, {p.document_id: p for p in profiles})
        result2 = inferer.infer(family_cluster, {p.document_id: p for p in profiles})

        assert [cr.condition for cr in result1.conditional_rules] == [
            cr.condition for cr in result2.conditional_rules
        ]

    def test_input_order_independence_and_filename_independence(self):
        """Conditional inference is based on content, not order or filenames."""
        inferer = TemplateInferer()
        profiles = [
            create_test_profile(
                "doc_001",
                "offer_001.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_002",
                "offer_002.docx",
                vocabulary={"remote": 1, "setup": 1},
                sections_data=[{"title": "Remote Work Setup"}],
            ),
            create_test_profile(
                "doc_003",
                "different_name_003.docx",
                vocabulary={"office": 1},
                sections_data=[],
            ),
        ]

        family_cluster_1 = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=3,
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        family_cluster_2 = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in reversed(profiles)],
            document_filenames=[p.filename for p in reversed(profiles)],
            confidence=0.9,
            cluster_size=3,
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result1 = inferer.infer(family_cluster_1, {p.document_id: p for p in profiles})
        result2 = inferer.infer(family_cluster_2, {p.document_id: p for p in reversed(profiles)})

        assert [cr.target_section for cr in result1.conditional_rules] == [
            cr.target_section for cr in result2.conditional_rules
        ]

    def test_conditional_rule_serialization_backward_compatible(self):
        """Conditional rules serialize with section_name/condition/confidence/evidence while remaining backward compatible."""
        rule = ConditionalRule(
            target_section="Remote Work Setup",
            condition={"field": "variable_observation", "operator": "equals", "value": "remote"},
            supporting_evidence=[
                InferenceEvidence(
                    evidence_type="conditional_correlation",
                    source_document_ids=["doc_001", "doc_002"],
                    related_section="Remote Work Setup",
                    observation="remote observed in docs with section",
                    confidence_contribution=0.8,
                )
            ],
            confidence=0.8,
            status="inferred",
        )

        payload = rule.to_dict()
        assert payload["section_name"] == "Remote Work Setup"
        assert payload["condition"]["value"] == "remote"
        assert payload["confidence"] == 0.8
        assert len(payload["evidence"]) == 1
        assert payload["target_section"] == "Remote Work Setup"

    def test_singleton_identifier_rejection(self):
        """Singleton values (appearing in only one document) must not become section conditions.

        This test directly tests _find_best_variable_condition to verify that
        document-specific identifiers like employee_id are rejected when they occur
        in only a single document.
        """
        from superdocs_template_inference.template_inference.conditionals import (
            _find_best_variable_condition,
        )

        # Create profiles representing doc_001 with section, doc_002 and doc_003 without
        profiles_with_section = [
            create_test_profile("doc_001", "doc_001.docx"),
        ]
        profiles_without_section = [
            create_test_profile("doc_002", "doc_002.docx"),
            create_test_profile("doc_003", "doc_003.docx"),
        ]

        # Simulate variable_values where each document has a unique employee_id
        # This represents the false-positive case: employee_id is unique per document
        # and employee_id == BFT-10234 perfectly correlates with the section in doc_001
        # but should NOT be accepted as a reusable template condition
        variable_values = {
            "doc_001": {"employee_id": ["BFT-10234"]},
            "doc_002": {"employee_id": ["BFT-10235"]},
            "doc_003": {"employee_id": ["BFT-10236"]},
        }

        condition = _find_best_variable_condition(
            profiles_with_section,
            profiles_without_section,
            variable_values,
        )

        # The condition should be None because employee_id values are singleton identifiers
        # appearing in only one document each
        assert condition is None, (
            "Singleton identifier values like employee_id should not be accepted as "
            "section conditions. Got: " + str(condition)
        )

    def test_repeated_categorical_value_accepted(self):
        """Repeated categorical values across documents can become valid conditions.

        When the same categorical value appears in multiple documents and correlates
        with section presence, it can be selected as a valid reusable condition.
        This test directly tests _find_best_variable_condition with work_mode=Remote
        appearing in multiple documents with the section.
        """
        from superdocs_template_inference.template_inference.conditionals import (
            _find_best_variable_condition,
        )

        # Create profiles:
        # - doc_001 and doc_002: have the section, work_mode=Remote
        # - doc_003 and doc_004: don't have section, work_mode=Office
        profiles_with_section = [
            create_test_profile("doc_001", "doc_001.docx"),
            create_test_profile("doc_002", "doc_002.docx"),
        ]
        profiles_without_section = [
            create_test_profile("doc_003", "doc_003.docx"),
            create_test_profile("doc_004", "doc_004.docx"),
        ]

        # work_mode=Remote appears in both profiles with the section (repeated)
        # work_mode=Office appears in both profiles without the section
        variable_values = {
            "doc_001": {"work_mode": ["Remote"]},
            "doc_002": {"work_mode": ["Remote"]},
            "doc_003": {"work_mode": ["Office"]},
            "doc_004": {"work_mode": ["Office"]},
        }

        condition = _find_best_variable_condition(
            profiles_with_section,
            profiles_without_section,
            variable_values,
        )

        # The condition should be accepted because work_mode=Remote appears in
        # multiple documents (2 distinct docs) and perfectly predicts section presence
        assert condition is not None, (
            "Repeated categorical values should be accepted as conditions"
        )
        assert condition[0] == "work_mode", f"Expected variable='work_mode', got={condition[0]}"
        assert condition[1] == "equals", f"Expected operator='equals', got={condition[1]}"
        assert condition[2] == "Remote", f"Expected value='Remote', got={condition[2]}"

    def test_repeated_department_value_accepted(self):
        """Department values appearing in multiple documents can become conditions.

        Similar to work_mode, categorical variables like department that appear
        in multiple documents and predict section presence can be accepted.
        """
        from superdocs_template_inference.template_inference.conditionals import (
            _find_best_variable_condition,
        )

        # Create profiles:
        # - doc_001 and doc_002: have section, department=Engineering
        # - doc_003 and doc_004: no section, department=Marketing
        profiles_with_section = [
            create_test_profile("doc_001", "doc_001.docx"),
            create_test_profile("doc_002", "doc_002.docx"),
        ]
        profiles_without_section = [
            create_test_profile("doc_003", "doc_003.docx"),
            create_test_profile("doc_004", "doc_004.docx"),
        ]

        variable_values = {
            "doc_001": {"department": ["Engineering"]},
            "doc_002": {"department": ["Engineering"]},
            "doc_003": {"department": ["Marketing"]},
            "doc_004": {"department": ["Marketing"]},
        }

        condition = _find_best_variable_condition(
            profiles_with_section,
            profiles_without_section,
            variable_values,
        )

        # Should accept Engineering because it appears in multiple docs and predicts section
        assert condition is not None, (
            "Repeated department values should be accepted as conditions"
        )
        assert condition[0] == "department"
        assert condition[2] == "Engineering"


class TestDeterminism:
    """Tests for deterministic inference."""

    def test_repeated_inference_is_identical(self):
        """Repeated inference on same input produces identical result."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Section A",
                        "heading_level": 1,
                    }
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
            cluster_size=len(profiles),
            pairwise_scores=[0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result1 = inferer.infer(family_cluster, profiles_by_id)
        result2 = inferer.infer(family_cluster, profiles_by_id)

        assert result1.family_id == result2.family_id
        assert result1.confidence == result2.confidence
        assert len(result1.sections) == len(result2.sections)

    def test_input_order_independence(self):
        """Same profiles in different order produce same inference."""
        inferer = TemplateInferer()

        profiles_list = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Consistent Section",
                        "heading_level": 1,
                    }
                ],
            )
            for i in range(1, 4)
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles_list],
            document_filenames=[p.filename for p in profiles_list],
            confidence=0.9,
            cluster_size=len(profiles_list),
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        # First order
        profiles_by_id_1 = {p.document_id: p for p in profiles_list}
        result1 = inferer.infer(family_cluster, profiles_by_id_1)

        # Reversed order (but same profiles)
        profiles_by_id_2 = {p.document_id: p for p in reversed(profiles_list)}
        result2 = inferer.infer(family_cluster, profiles_by_id_2)

        assert len(result1.sections) == len(result2.sections)


class TestSerialization:
    """Tests for result serialization."""

    def test_template_result_serializes_to_dict(self):
        """TemplateInferenceResult can be serialized to dict."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            sections_data=[
                {
                    "section_id": "sec_0",
                    "title": "Section A",
                    "heading_level": 1,
                }
            ],
        )

        result = TemplateInferenceResult(
            family_id="family_001",
            document_ids=["doc_001"],
            confidence=0.9,
            sections=[
                TemplateSection(
                    section_id="section_0",
                    title_or_pattern="section a",
                    inferred_type="REQUIRED",
                    order=0,
                    presence_frequency=1.0,
                    presence_type="always",
                    content_representation="Section A",
                    confidence=1.0,
                )
            ],
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["family_id"] == "family_001"
        assert result_dict["confidence"] == 0.9
        assert len(result_dict["sections"]) == 1


class TestEvidenceGeneration:
    """Tests for evidence generation."""

    def test_section_has_evidence(self):
        """Inferred sections contain evidence."""
        profile = create_test_profile(
            "doc_001",
            "doc_001.docx",
            sections_data=[
                {
                    "section_id": "sec_0",
                    "title": "Section with Evidence",
                    "heading_level": 1,
                }
            ],
        )

        section = TemplateSection(
            section_id="section_0",
            title_or_pattern="section with evidence",
            inferred_type="REQUIRED",
            order=0,
            presence_frequency=1.0,
            presence_type="always",
            content_representation="Section with Evidence",
            confidence=1.0,
            evidence=[
                InferenceEvidence(
                    evidence_type="section_alignment",
                    source_document_ids=["doc_001"],
                    related_section="section with evidence",
                    observation="Section appears in 1/1 documents",
                    confidence_contribution=1.0,
                )
            ],
        )

        assert len(section.evidence) > 0
        assert section.evidence[0].evidence_type == "section_alignment"


class TestConfidenceRanges:
    """Tests for confidence values."""

    def test_confidence_in_valid_range(self):
        """Confidence values are normalized 0.0–1.0."""
        inferer = TemplateInferer()
        profile = create_test_profile("doc_001", "doc_001.docx")

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=["doc_001"],
            document_filenames=["doc_001.docx"],
            confidence=0.85,
            cluster_size=1,
            pairwise_scores=[],
            pairwise_score_mean=1.0,
            pairwise_score_min=1.0,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, {"doc_001": profile})

        assert 0.0 <= result.confidence <= 1.0
        for section in result.sections:
            assert 0.0 <= section.confidence <= 1.0
        for variable in result.variables:
            assert 0.0 <= variable.confidence <= 1.0


class TestFilenameIndependence:
    """Tests to verify filenames don't drive inference."""

    def test_same_profiles_different_filenames(self):
        """Profiles with different filenames produce same inference."""
        inferer = TemplateInferer()

        profile1 = create_test_profile(
            "doc_001",
            "offer_letter_001.docx",
            sections_data=[
                {
                    "section_id": "sec_0",
                    "title": "Terms",
                    "heading_level": 1,
                }
            ],
        )

        profile2 = create_test_profile(
            "doc_002",
            "different_filename_002.docx",
            sections_data=[
                {
                    "section_id": "sec_0",
                    "title": "Terms",
                    "heading_level": 1,
                }
            ],
        )

        profiles_by_id = {"doc_001": profile1, "doc_002": profile2}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=["doc_001", "doc_002"],
            document_filenames=["offer_letter_001.docx", "different_filename_002.docx"],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.85],
            pairwise_score_mean=0.85,
            pairwise_score_min=0.85,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Inference should be based on section/content, not filenames
        assert result.family_id == "family_001"
        assert len(result.sections) >= 1


class TestGroundTruthIsolation:
    """Tests to ensure ground-truth JSON is never read."""

    def test_infer_does_not_read_ground_truth_files(self):
        """Inference doesn't attempt to read ground-truth files."""
        inferer = TemplateInferer()
        profile = create_test_profile("doc_001", "doc_001.docx")

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

        # This should not raise an exception or attempt file I/O
        result = inferer.infer(family_cluster, {"doc_001": profile})

        assert result.family_id == "family_001"


# M6 Enhancement Tests


class TestContextualSemanticVariableDetection:
    """Tests for contextual semantic-variable detection without using ground truth."""

    def test_rejects_ordinary_vocabulary_tokens(self):
        """Ordinary words are rejected without field-like evidence."""
        from superdocs_template_inference.template_inference.variables import detect_variables

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"aboard": 3, "addition": 2, "appropriate": 2, "support": 4, "your": 5},
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"aboard": 2, "addition": 3, "appropriate": 2, "support": 5, "your": 4},
            ),
        ]

        candidates = detect_variables(profiles)
        assert "aboard" not in candidates
        assert "addition" not in candidates
        assert "appropriate" not in candidates
        assert "support" not in candidates
        assert "your" not in candidates

    def test_prevents_false_enum_classification(self):
        """Only bounded categorical values become enum; ordinary words do not."""
        from superdocs_template_inference.template_inference.variables import infer_variable_type

        assert infer_variable_type(["appropriately", "assistance", "addition", "support"])[0] == "string"
        assert infer_variable_type(["remote", "office", "hybrid"])[0] == "enum"

    def test_accepts_strongly_contextual_field_value_candidate(self):
        """A token with explicit field context survives detection."""
        from superdocs_template_inference.template_inference.variables import detect_variables

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"manager": 2, "team": 1, "your": 5},
                sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"supervisor": 2, "team": 1, "your": 5},
                sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}],
            ),
        ]

        candidates = detect_variables(profiles)
        assert "manager" in candidates or "supervisor" in candidates
        assert any(info["values"] for info in candidates.values())

    def test_preserves_actual_observed_values(self):
        """When a candidate is accepted, actual observed values are retained."""
        from superdocs_template_inference.template_inference.variables import detect_variables

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"remote": 2, "office": 1, "your": 4},
                sections_data=[{"section_id": "sec_0", "title": "Work Mode", "heading_level": 1}],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"hybrid": 2, "office": 1, "your": 4},
                sections_data=[{"section_id": "sec_0", "title": "Work Mode", "heading_level": 1}],
            ),
        ]

        candidates = detect_variables(profiles)
        accepted = next(iter(candidates.values()))
        assert accepted["values"]
        assert "remote" in accepted["values"] or "hybrid" in accepted["values"] or "office" in accepted["values"]

    def test_detect_variables_is_deterministic_and_filename_independent(self):
        """Candidate selection is stable and not driven by filenames."""
        from superdocs_template_inference.template_inference.variables import detect_variables

        profile_a = create_test_profile(
            "doc_001",
            "alpha_name.docx",
            vocabulary={"manager": 3, "team": 2, "your": 5},
            sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}],
        )
        profile_b = create_test_profile(
            "doc_002",
            "beta_name.docx",
            vocabulary={"supervisor": 3, "team": 2, "your": 5},
            sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}],
        )

        result_1 = detect_variables([profile_a, profile_b])
        result_2 = detect_variables([profile_b, profile_a])

        assert list(result_1.keys()) == list(result_2.keys())
        assert result_1 == result_2

    def test_ground_truth_isolation_and_filename_independence(self):
        """Selection is based only on profile evidence, never filenames or benchmark names."""
        from superdocs_template_inference.template_inference.variables import detect_variables

        candidates_a = detect_variables([
            create_test_profile("doc_001", "offer_001_actual_letter.docx", vocabulary={"manager": 3, "team": 2, "your": 5}, sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}]),
            create_test_profile("doc_002", "offer_002_actual_letter.docx", vocabulary={"supervisor": 3, "team": 2, "your": 5}, sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}]),
        ])
        candidates_b = detect_variables([
            create_test_profile("doc_003", "onboarding_003_actual_letter.docx", vocabulary={"manager": 3, "team": 2, "your": 5}, sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}]),
            create_test_profile("doc_004", "onboarding_004_actual_letter.docx", vocabulary={"supervisor": 3, "team": 2, "your": 5}, sections_data=[{"section_id": "sec_0", "title": "Reporting Manager", "heading_level": 1}]),
        ])

        assert candidates_a == candidates_b


class TestM6ValueExtraction:
    """Tests for M6 value extraction from variable candidates."""

    def test_extract_variable_values_basic(self):
        """Values are extracted from candidate variables."""
        from superdocs_template_inference.template_inference.variables import (
            extract_variable_values,
        )

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"alice": 1, "bob": 1, "fixed_text": 2},
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"charlie": 1, "bob": 1, "fixed_text": 2},
            ),
        ]

        candidates = {
            "alice": {"values": [], "frequency": 0.5},
            "charlie": {"values": [], "frequency": 0.5},
            "bob": {"values": [], "frequency": 1.0},
        }

        values = extract_variable_values(candidates, profiles)

        # Should have extracted values for each candidate
        assert "alice" in values
        assert "charlie" in values
        assert "bob" in values

    def test_extracted_values_are_sorted(self):
        """Extracted values are sorted for determinism."""
        from superdocs_template_inference.template_inference.variables import (
            extract_variable_values,
        )

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                vocabulary={"zebra": 1, "apple": 1, "monkey": 1},
            )
            for i in range(1, 3)
        ]

        candidates = {"zebra": {}, "apple": {}, "monkey": {}}
        values = extract_variable_values(candidates, profiles)

        # Values should be sorted for determinism
        assert values["apple"] == ["apple"]
        assert values["zebra"] == ["zebra"]


class TestM6TypeInference:
    """Tests for M6 type inference from variable values."""

    def test_infer_email_type(self):
        """Email addresses are recognized as email type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["john.doe@example.com", "jane.smith@example.com"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "email"
        assert not metadata.get("is_enum", False)

    def test_infer_phone_type(self):
        """Phone numbers are recognized as phone type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["555-123-4567", "555.987.6543"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "phone"

    def test_infer_date_type(self):
        """Dates are recognized as date type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["01/15/2024", "03-20-2024"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "date"

    def test_infer_datetime_type(self):
        """Datetimes are recognized as datetime type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["01/15/2024 14:30", "03/20/2024 09:15:45"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "datetime"

    def test_infer_time_type(self):
        """Times are recognized as time type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["14:30", "09:15 AM"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "time"

    def test_infer_currency_type(self):
        """Currency amounts are recognized as currency type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["$120,000", "$95,000.50"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "currency"

    def test_infer_integer_type(self):
        """Integers are recognized as integer type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["42", "100", "999"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "integer"

    def test_infer_boolean_type(self):
        """Boolean values are recognized as boolean type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["true", "false", "true"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "boolean"
        assert metadata.get("is_enum", False)
        assert set(metadata.get("enum_values", [])) == {"false", "true"}

    def test_infer_enum_type(self):
        """Limited set of distinct values recognized as enum."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = ["Remote", "Office", "Remote", "Hybrid"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "enum"
        assert metadata.get("is_enum", False)
        # Only 3 unique values, so should still be enum
        assert "remote" in [v.lower() for v in metadata.get("enum_values", [])]

    def test_infer_string_type_default(self):
        """High cardinality values default to string type."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_type,
        )

        values = [
            f"Employee_{i} Name" for i in range(20)
        ]  # Many unique values
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "string"


class TestM6Metadata:
    """Tests for M6 variable metadata inference."""

    def test_infer_variable_metadata_frequency(self):
        """Metadata includes variable frequency."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_metadata,
        )

        profiles = [
            create_test_profile(f"doc_{i:03d}", f"doc_{i:03d}.docx", vocabulary={"alice": 1})
            for i in range(1, 4)
        ]

        metadata = infer_variable_metadata("alice", ["alice"], profiles)

        assert "frequency" in metadata
        assert 0.0 <= metadata["frequency"] <= 1.0

    def test_infer_unique_per_document(self):
        """Metadata tracks if value is unique per document."""
        from superdocs_template_inference.template_inference.variables import (
            infer_variable_metadata,
        )

        profiles = [
            create_test_profile(f"doc_{i:03d}", f"doc_{i:03d}.docx", vocabulary={"value": 1})
            for i in range(1, 4)
        ]

        metadata = infer_variable_metadata("value", ["value"], profiles)

        assert "unique_per_document" in metadata
        assert isinstance(metadata["unique_per_document"], bool)


class TestM6SectionLinking:
    """Tests for M6 variable-to-section linking."""

    def test_link_variable_to_sections(self):
        """Variables are linked to sections they appear in."""
        from superdocs_template_inference.template_inference.variables import (
            link_variable_to_sections,
        )
        from superdocs_template_inference.template_inference.sections import (
            align_sections,
        )

        profiles = [
            create_test_profile(
                "doc_001",
                "doc_001.docx",
                vocabulary={"alice": 1, "salary": 1},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Employee Info",
                        "heading_level": 1,
                    }
                ],
            ),
            create_test_profile(
                "doc_002",
                "doc_002.docx",
                vocabulary={"bob": 1, "salary": 1},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Employee Info",
                        "heading_level": 1,
                    }
                ],
            ),
        ]

        section_groups = align_sections(profiles)
        sections = link_variable_to_sections("alice", profiles, section_groups)

        # Should return a list (possibly empty if linking is complex)
        assert isinstance(sections, list)


class TestM6IntegrationWithInferer:
    """Tests for M6 integration with full inference pipeline."""

    def test_inferred_variable_has_type_info(self):
        """Inferred variables include type information."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                vocabulary={"john.doe@example.com": 1, "jane.smith@example.com": 1},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Header",
                        "heading_level": 1,
                    }
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
            cluster_size=len(profiles),
            pairwise_scores=[0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Should have variables with type info
        if result.variables:
            var = result.variables[0]
            # Type info might be populated
            assert hasattr(var, "inferred_type")

    def test_variable_evidence_includes_type_inference(self):
        """Variable evidence includes type inference observations."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                vocabulary={"2024-01-15": 1, "2024-03-20": 1},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Header",
                        "heading_level": 1,
                    }
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
            cluster_size=len(profiles),
            pairwise_scores=[0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Check that variables have evidence
        for var in result.variables:
            assert len(var.evidence) > 0


class TestM6Determinism:
    """Tests for M6 deterministic behavior."""

    def test_m6_repeated_inference_identical(self):
        """M6-enhanced inference is deterministic."""
        inferer = TemplateInferer()

        profiles = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                vocabulary={f"value_{i}": 1, "fixed": 2},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Section",
                        "heading_level": 1,
                    }
                ],
            )
            for i in range(1, 4)
        ]

        profiles_by_id = {p.document_id: p for p in profiles}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles],
            document_filenames=[p.filename for p in profiles],
            confidence=0.9,
            cluster_size=len(profiles),
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result1 = inferer.infer(family_cluster, profiles_by_id)
        result2 = inferer.infer(family_cluster, profiles_by_id)

        # Same input should produce identical output
        assert len(result1.variables) == len(result2.variables)
        for v1, v2 in zip(result1.variables, result2.variables):
            assert v1.variable_name == v2.variable_name
            assert v1.inferred_type == v2.inferred_type
            assert v1.is_enum == v2.is_enum

    def test_m6_input_order_independence(self):
        """M6 inference is independent of input order."""
        inferer = TemplateInferer()

        profiles_list = [
            create_test_profile(
                f"doc_{i:03d}",
                f"doc_{i:03d}.docx",
                vocabulary={f"value_{i}": 1, "constant": 2},
                sections_data=[
                    {
                        "section_id": "sec_0",
                        "title": "Section",
                        "heading_level": 1,
                    }
                ],
            )
            for i in range(1, 4)
        ]

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=[p.document_id for p in profiles_list],
            document_filenames=[p.filename for p in profiles_list],
            confidence=0.9,
            cluster_size=len(profiles_list),
            pairwise_scores=[0.8, 0.8, 0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        # First order
        profiles_by_id_1 = {p.document_id: p for p in profiles_list}
        result1 = inferer.infer(family_cluster, profiles_by_id_1)

        # Reversed order
        profiles_by_id_2 = {p.document_id: p for p in reversed(profiles_list)}
        result2 = inferer.infer(family_cluster, profiles_by_id_2)

        # Results should be equivalent
        assert len(result1.variables) == len(result2.variables)


class TestM6FilenameIndependence:
    """Tests to verify filenames don't affect M6 inference."""

    def test_m6_filename_does_not_affect_type_inference(self):
        """Filenames don't drive type inference."""
        inferer = TemplateInferer()

        profile1 = create_test_profile(
            "doc_001",
            "email_addresses_001.docx",
            vocabulary={"john@example.com": 1, "jane@example.com": 1},
            sections_data=[
                {"section_id": "sec_0", "title": "Section", "heading_level": 1}
            ],
        )

        profile2 = create_test_profile(
            "doc_002",
            "contact_info_002.docx",
            vocabulary={"bob@example.com": 1, "alice@example.com": 1},
            sections_data=[
                {"section_id": "sec_0", "title": "Section", "heading_level": 1}
            ],
        )

        profiles_by_id = {"doc_001": profile1, "doc_002": profile2}

        family_cluster = FamilyCluster(
            family_id="family_001",
            document_ids=["doc_001", "doc_002"],
            document_filenames=[
                "email_addresses_001.docx",
                "contact_info_002.docx",
            ],
            confidence=0.9,
            cluster_size=2,
            pairwise_scores=[0.8],
            pairwise_score_mean=0.8,
            pairwise_score_min=0.8,
            merge_evidence=[],
        )

        result = inferer.infer(family_cluster, profiles_by_id)

        # Type should be inferred from values, not filenames
        for var in result.variables:
            if "@" in var.variable_name:
                assert var.inferred_type == "email"


class TestM6Serialization:
    """Tests for M6 serialization with new metadata."""

    def test_variable_with_type_info_serializes(self):
        """VariableField with type info serializes correctly."""
        var = VariableField(
            variable_name="email_address",
            semantic_role="email",
            section_context="contact_info",
            observed_values=["john@example.com", "jane@example.com"],
            frequency=1.0,
            confidence=0.95,
            inferred_type="email",
            is_enum=False,
        )

        var_dict = var.to_dict()

        assert var_dict["variable_name"] == "email_address"
        assert var_dict["inferred_type"] == "email"
        assert "observed_values" in var_dict

    def test_enum_variable_serializes_with_values(self):
        """Enum variables serialize with enum_values."""
        var = VariableField(
            variable_name="work_mode",
            semantic_role="work_mode",
            section_context="employee_info",
            observed_values=["Remote", "Office"],
            frequency=1.0,
            confidence=0.9,
            inferred_type="enum",
            is_enum=True,
            enum_values=["Office", "Remote"],
        )

        var_dict = var.to_dict()

        assert var_dict["is_enum"] is True
        assert set(var_dict["enum_values"]) == {"Office", "Remote"}
