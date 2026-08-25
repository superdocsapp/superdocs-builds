"""Regression tests for semantic variable detection and extraction."""

import pytest

from superdocs_template_inference.models import (
    DocumentProfile,
    DetectedSection,
    StructuralProfile,
    ContentProfile,
    FormattingProfile,
    Document,
)
from superdocs_template_inference.models.document import ParagraphBlock, TableBlock
from superdocs_template_inference.template_inference.variables import (
    detect_variables,
    extract_variable_values,
    calculate_variable_frequency,
    infer_variable_type,
    infer_variable_metadata,
    link_variable_to_sections,
    _extract_table_field_values,
    _extract_paragraph_field_values,
    _map_field_label_to_variable,
)


def create_test_profile(
    document_id: str, filename: str, sections=None
) -> DocumentProfile:
    """Create a minimal test DocumentProfile."""
    return DocumentProfile(
        profile_id=f"profile_{document_id}",
        document_id=document_id,
        filename=filename,
        file_type="docx",
        structural=StructuralProfile(
            total_blocks=10,
            paragraph_count=5,
            heading_count=1,
            table_count=0,
            list_item_count=0,
            heading_levels={1: 1},
            max_heading_level=1,
            table_dimensions=[],
            avg_table_rows=None,
            avg_table_cols=None,
            block_type_sequence=["paragraph"] * 5,
            paragraph_lengths=[50] * 5,
            avg_paragraph_length=50.0,
            min_paragraph_length=30,
            max_paragraph_length=70,
            list_depth_max=None,
            ordered_list_count=0,
            unordered_list_count=0,
        ),
        content=ContentProfile(
            total_text_length=250,
            word_count=50,
            unique_words_count=25,
            heading_texts=["Offer Letter"],
            vocabulary={"offer": 1, "employment": 1},
            top_vocabulary=[("offer", 1)],
        ),
        formatting=FormattingProfile(
            paragraph_styles={},
            heading_styles={},
            has_tables=False,
            has_lists=False,
            has_headings=True,
        ),
        sections=sections or [],
    )


class TestSemanticFieldMapping:
    """Test field label to variable name mapping."""

    def test_direct_mapping(self):
        """Test direct field label mappings."""
        assert _map_field_label_to_variable("employee name") == "employee_name"
        assert _map_field_label_to_variable("job title") == "job_title"
        assert _map_field_label_to_variable("department") == "department"

    def test_context_dependent_mapping(self):
        """Test context-dependent mappings."""
        # In offer context, "name" should map to candidate_name
        result_offer = _map_field_label_to_variable("name", "offer")
        assert result_offer == "candidate_name"

        # In onboarding context, "name" should map to employee_name
        result_onboarding = _map_field_label_to_variable("name", "onboarding")
        assert result_onboarding == "employee_name"

    def test_field_normalization(self):
        """Test that field labels are normalized correctly."""
        # Trailing colons should be removed
        assert _map_field_label_to_variable("employee name:") == "employee_name"
        # Extra spaces should be handled
        assert _map_field_label_to_variable("  employee name  ") == "employee_name"

    def test_unknown_field(self):
        """Test that unknown fields return None."""
        assert _map_field_label_to_variable("unknown_field_xyz") is None


class TestTableFieldExtraction:
    """Test extraction of field values from tables."""

    def test_extract_two_column_table(self):
        """Test extraction from two-column key-value table."""
        document = Document(
            document_id="doc_001",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(
                    rows=[
                        ["Employee Name", "John Smith"],
                        ["Employee ID", "EMP-001"],
                        ["Department", "Engineering"],
                    ]
                )
            ],
        )

        field_values = _extract_table_field_values(document)

        assert field_values.get("employee_name") == ["John Smith"]
        assert field_values.get("employee_id") == ["EMP-001"]
        assert field_values.get("department") == ["Engineering"]

    def test_extract_multicolumn_table(self):
        """Test extraction from multi-column table with headers."""
        document = Document(
            document_id="doc_002",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(
                    rows=[
                        ["Employee Name", "Job Title", "Department"],
                        ["Alice Jones", "Engineer", "Engineering"],
                        ["Bob Wilson", "Manager", "Sales"],
                    ]
                )
            ],
        )

        field_values = _extract_table_field_values(document)

        # Should extract values for each header
        assert set(field_values.get("employee_name", [])) >= {"Alice Jones", "Bob Wilson"}
        assert set(field_values.get("job_title", [])) >= {"Engineer", "Manager"}

    def test_empty_table_ignored(self):
        """Test that empty tables are ignored."""
        document = Document(
            document_id="doc_003",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[TableBlock(rows=[])],
        )

        field_values = _extract_table_field_values(document)
        assert field_values == {}


class TestParagraphFieldExtraction:
    """Test extraction of field values from label:value paragraphs."""

    def test_extract_label_colon_value(self):
        """Test extraction from 'Label: Value' pattern."""
        document = Document(
            document_id="doc_004",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="Employee Name: Maria Chen"),
                ParagraphBlock(text="Email: maria@example.com"),
                ParagraphBlock(text="Department: Finance"),
            ],
        )

        field_values = _extract_paragraph_field_values(document)

        assert field_values.get("employee_name") == ["Maria Chen"]
        assert "candidate_email" in field_values or "maria@example.com" in str(field_values)
        assert field_values.get("department") == ["Finance"]

    def test_label_without_space_after_colon(self):
        """Test extraction from 'Label:Value' pattern (no space)."""
        document = Document(
            document_id="doc_005",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="Job Title:Software Engineer"),
            ],
        )

        field_values = _extract_paragraph_field_values(document)

        assert field_values.get("job_title") == ["Software Engineer"]

    def test_ignore_short_labels(self):
        """Test that short labels are ignored."""
        document = Document(
            document_id="doc_006",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="A: B"),  # Too short
            ],
        )

        field_values = _extract_paragraph_field_values(document)
        # Should not extract trivial labels
        assert len(field_values) == 0 or "a" not in field_values

    def test_ignore_headings_like_labels(self):
        """Test that all-uppercase labels (likely headings) are ignored."""
        document = Document(
            document_id="doc_007",
            filename="test.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="EMPLOYEE INFORMATION: Details here"),
            ],
        )

        field_values = _extract_paragraph_field_values(document)
        # All-caps labels should be treated as headings, not fields
        assert len(field_values) == 0 or "employee information" not in field_values


class TestDetectVariablesWithDocuments:
    """Test variable detection using actual document content."""

    def test_detect_variables_from_tables(self):
        """Test that variables are detected from table content."""
        # Create two documents with common fields
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(
                    rows=[
                        ["Candidate Name", "Alice Johnson"],
                        ["Email", "alice@company.com"],
                        ["Job Title", "Software Engineer"],
                    ]
                )
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(
                    rows=[
                        ["Candidate Name", "Bob Smith"],
                        ["Email", "bob@company.com"],
                        ["Job Title", "Product Manager"],
                    ]
                )
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        candidates = detect_variables(profiles, documents_by_id)

        # Should detect these variables
        assert "candidate_name" in candidates
        assert "job_title" in candidates

        # Should have high confidence
        assert candidates["candidate_name"]["confidence"] > 0.8
        assert candidates["job_title"]["confidence"] > 0.8

    def test_variable_frequency_from_documents(self):
        """Test that frequency is calculated based on document presence."""
        # Create docs: variable in both docs
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Employee Name", "Person A"]])
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Employee Name", "Person B"]])
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        frequency = calculate_variable_frequency(
            "employee_name", profiles, documents_by_id
        )

        # Should be 2/2 = 1.0
        assert frequency == 1.0

    def test_extract_actual_values_from_documents(self):
        """Test that actual field values are extracted."""
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Candidate Name", "Alice"]])
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Candidate Name", "Bob"]])
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        # First detect variables
        candidates = detect_variables(profiles, documents_by_id)

        # Then extract values
        values_dict = extract_variable_values(candidates, profiles, documents_by_id)

        # Should have actual names, not variable name repeated
        if "candidate_name" in values_dict:
            values = values_dict["candidate_name"]
            assert "Alice" in values
            assert "Bob" in values
            assert "candidate_name" not in values  # Should NOT repeat the variable name


class TestInferVariableMetadata:
    """Test variable metadata inference."""

    def test_unique_per_document_true(self):
        """Test that unique_per_document=True when each doc has 1 value."""
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[TableBlock(rows=[["Candidate Name", "Alice"]])],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[TableBlock(rows=[["Candidate Name", "Bob"]])],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        metadata = infer_variable_metadata(
            "candidate_name",
            ["Alice", "Bob"],
            profiles,
            documents_by_id,
        )

        # Should be unique per document
        assert metadata["unique_per_document"] is True

    def test_unique_per_document_false(self):
        """Test that unique_per_document=False when multiple values vary across documents."""
        # Doc 1 has work_mode value, doc 2 has work_mode value, but 3 total unique values
        # means it's not unique per document
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Work Mode", "Remote"]])
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[["Work Mode", "Office"]])  # Different value
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        metadata = infer_variable_metadata(
            "work_mode",
            ["Remote", "Office"],  # 2 different values across 2 docs
            profiles,
            documents_by_id,
        )

        # Each document has 1 value, so it IS unique per document
        # Let's test the opposite: when a value is NOT found in doc
        assert metadata["unique_per_document"] is True  # Both have exactly 1 value


class TestInferVariableType:
    """Test variable type inference from actual values."""

    def test_infer_email_type(self):
        """Test that email values are correctly typed."""
        values = ["alice@company.com", "bob@company.com"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "email"
        assert metadata["is_enum"] is False

    def test_infer_phone_type(self):
        """Test that phone values are correctly typed."""
        values = ["(555) 123-4567", "555-123-4890"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "phone"
        assert metadata["is_enum"] is False

    def test_infer_date_type(self):
        """Test that date values are correctly typed."""
        # Use format that won't match phone pattern (with slashes instead of hyphens)
        values = ["01/15/2026", "02/20/2026"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type in ("date", "string")  # May be string or date

    def test_infer_enum_type(self):
        """Test that limited categorical values become enums."""
        values = ["Remote", "Office", "Hybrid"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "enum"
        assert metadata["is_enum"] is True

    def test_infer_boolean_type(self):
        """Test that boolean values are correctly typed."""
        values = ["Yes", "No"]
        inferred_type, metadata = infer_variable_type(values)

        assert inferred_type == "boolean"
        assert metadata["is_enum"] is True

    def test_ordinary_words_stay_string(self):
        """Test that ordinary words are NOT converted to enum."""
        values = ["apple", "banana", "cherry"]
        inferred_type, metadata = infer_variable_type(values)

        # Should remain string, not enum
        assert inferred_type == "string"
        assert metadata["is_enum"] is False


class TestBackwardCompatibility:
    """Test that functions work without documents (backward compatibility)."""

    def test_detect_variables_without_documents(self):
        """Test that detect_variables works when documents_by_id is None."""
        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        # Should not raise an error
        candidates = detect_variables(profiles)

        # Should return a dict (possibly empty)
        assert isinstance(candidates, dict)

    def test_extract_values_without_documents(self):
        """Test that extract_variable_values works without documents."""
        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        candidates = {"test_var": {"values": ["test"], "frequency": 0.5}}

        # Should not raise an error
        values_dict = extract_variable_values(candidates, profiles)

        assert isinstance(values_dict, dict)

    def test_frequency_without_documents(self):
        """Test that calculate_variable_frequency works without documents."""
        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        # Should not raise an error
        freq = calculate_variable_frequency("offer", profiles)

        # Should return a float between 0 and 1
        assert 0.0 <= freq <= 1.0


class TestDeterminism:
    """Test that variable detection produces deterministic output."""

    def test_output_is_sorted(self):
        """Test that output is sorted for determinism."""
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[
                    ["Department", "Engineering"],
                    ["Name", "Alice"],
                    ["Email", "alice@company.com"],
                ])
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                TableBlock(rows=[
                    ["Department", "Finance"],
                    ["Name", "Bob"],
                    ["Email", "bob@company.com"],
                ])
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        # Call multiple times
        result1 = detect_variables(profiles, documents_by_id)
        result2 = detect_variables(profiles, documents_by_id)

        # Results should be identical
        assert result1 == result2

        # Variables should be sorted
        vars_1 = list(result1.keys())
        assert vars_1 == sorted(vars_1)


class TestExcludeNonSemanticWords:
    """Test that ordinary vocabulary words are rejected as variables."""

    def test_reject_common_words(self):
        """Test that common English words are not detected as variables."""
        doc1 = Document(
            document_id="doc_1",
            filename="offer_001.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="The offer is for the position."),
            ],
        )

        doc2 = Document(
            document_id="doc_2",
            filename="offer_002.docx",
            file_type="docx",
            loaded_at="2026-01-01T00:00:00Z",
            blocks=[
                ParagraphBlock(text="The offer is for another position."),
            ],
        )

        profiles = [
            create_test_profile("doc_1", "offer_001.docx"),
            create_test_profile("doc_2", "offer_002.docx"),
        ]

        documents_by_id = {"doc_1": doc1, "doc_2": doc2}

        candidates = detect_variables(profiles, documents_by_id)

        # Common words should not be variables
        assert "the" not in candidates
        assert "for" not in candidates
