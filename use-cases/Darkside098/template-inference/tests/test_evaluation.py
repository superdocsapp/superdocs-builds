"""Focused tests for the evaluation layer."""

from __future__ import annotations

from superdocs_template_inference.evaluation import (
    TemplateEvaluator,
    canonical_condition,
    conditional_rule_score,
    load_ground_truth,
    normalize_name,
    section_f1_score,
    section_order_score,
    variable_score,
)
from superdocs_template_inference.template_inference.result import TemplateSection


def test_normalize_name_and_condition_canonicalization():
    assert normalize_name("Remote Work Setup") == "remote_work_setup"
    assert canonical_condition({"field": "work_mode", "operator": "==", "value": "Remote"}) == "work_mode|==|remote"


def test_section_order_score_gives_partial_credit():
    expected = ["company_header", "offer_title", "conditions_of_employment"]
    predicted = ["offer_title", "company_header", "conditions_of_employment"]
    score = section_order_score(expected, predicted)
    assert 0.0 < score < 1.0


def test_variable_score_handles_name_and_type_overlap():
    expected = [
        {"variable_name": "employee_name", "inferred_type": "string"},
        {"variable_name": "department", "inferred_type": "enum"},
    ]
    predicted = [
        {"variable_name": "employee_name", "inferred_type": "string"},
        {"variable_name": "team_name", "inferred_type": "string"},
    ]
    score = variable_score(expected, predicted)
    assert 0.0 < score < 1.0


def test_conditional_rule_score_uses_canonical_structured_conditions():
    expected = [{"target_section": "remote_work_setup", "condition": {"field": "work_mode", "operator": "==", "value": "Remote"}}]
    predicted = [{"target_section": "remote_work_setup", "condition": {"field": "work_mode", "operator": "==", "value": "remote"}}]
    score = conditional_rule_score(expected, predicted)
    assert score == 1.0


def test_load_ground_truth_reads_real_fixture_file():
    payload = load_ground_truth("offer")
    assert payload["document_family"] == "employee_offer_letter"
    assert "company_header" in payload["fixed_sections"]


def test_template_evaluator_reports_full_summary_for_generic_prediction():
    ground_truth = load_ground_truth("offer")
    prediction = {
        "family_id": "employee_offer_letter",
        "document_ids": [f"{idx:03d}" for idx in range(1, 13)],
        "sections": [
            {"title_or_pattern": "company_header"},
            {"title_or_pattern": "contact_bar"},
            {"title_or_pattern": "offer_title"},
            {"title_or_pattern": "date_and_reference"},
            {"title_or_pattern": "candidate_information"},
            {"title_or_pattern": "greeting"},
            {"title_or_pattern": "introduction"},
            {"title_or_pattern": "position_details"},
            {"title_or_pattern": "compensation_and_benefits"},
            {"title_or_pattern": "remote_work_arrangement", "conditional_info": {"field": "employment_type"}},
            {"title_or_pattern": "conditions_of_employment"},
            {"title_or_pattern": "acceptance"},
            {"title_or_pattern": "closing"},
            {"title_or_pattern": "signature_block"},
        ],
        "variables": [
            {"variable_name": "candidate_name", "inferred_type": "string"},
            {"variable_name": "job_title", "inferred_type": "string"},
            {"variable_name": "employment_type", "inferred_type": "enum"},
            {"variable_name": "annual_ctc", "inferred_type": "currency"},
        ],
        "conditional_rules": [
            {"target_section": "remote_work_arrangement", "condition": {"field": "employment_type", "operator": "==", "value": "Remote"}},
        ],
    }

    evaluator = TemplateEvaluator()
    report = evaluator.evaluate(prediction, ground_truth)

    assert 0.0 <= report.overall_score <= 1.0
    assert report.metrics["family_detection"].score == 1.0
    assert "section_detection" in report.metrics
    assert "section_ordering" in report.metrics
    assert "variable_detection" in report.metrics
    assert "conditional_rule_inference" in report.metrics


def test_section_f1_score_handles_normalized_matches():
    expected = ["Remote Work Setup", "Office Access Desk Setup"]
    predicted = ["remote_work_setup", "office_access_desk_setup"]
    assert section_f1_score(expected, predicted) == 1.0


def test_extract_predicted_sections_handles_template_section_objects():
    evaluator = TemplateEvaluator()
    prediction = {
        "sections": [
            TemplateSection(
                section_id="sec_1",
                title_or_pattern="Company Header",
                inferred_type="REQUIRED",
                order=0,
                presence_frequency=1.0,
                presence_type="always",
                content_representation="Company Header",
            ),
            TemplateSection(
                section_id="sec_2",
                title_or_pattern="Offer Title",
                inferred_type="REQUIRED",
                order=1,
                presence_frequency=1.0,
                presence_type="always",
                content_representation="Offer Title",
            ),
        ]
    }

    assert evaluator._extract_predicted_sections(prediction) == ["company_header", "offer_title"]


def test_extract_predicted_sections_preserves_dictionary_fallbacks():
    evaluator = TemplateEvaluator()
    prediction = {
        "sections": [
            {"title_or_pattern": "Greeting"},
            {"section_name": "Candidate Information"},
            {"name": "Position Details"},
            {"title": "Closing"},
        ]
    }

    assert evaluator._extract_predicted_sections(prediction) == [
        "greeting",
        "candidate_information",
        "position_details",
        "closing",
    ]


def test_extract_predicted_order_handles_template_section_objects():
    evaluator = TemplateEvaluator()
    prediction = {
        "sections": [
            TemplateSection(
                section_id="section_0",
                title_or_pattern="employment_offer_letter",
                inferred_type="REQUIRED",
                order=0,
                presence_frequency=1.0,
                presence_type="always",
                content_representation="Employment Offer Letter",
            ),
            TemplateSection(
                section_id="section_1",
                title_or_pattern="position_details",
                inferred_type="REQUIRED",
                order=1,
                presence_frequency=1.0,
                presence_type="always",
                content_representation="Position Details",
            ),
            TemplateSection(
                section_id="section_2",
                title_or_pattern="compensation_and_benefits",
                inferred_type="REQUIRED",
                order=2,
                presence_frequency=1.0,
                presence_type="always",
                content_representation="Compensation and Benefits",
            ),
        ]
    }

    assert evaluator._extract_predicted_order(prediction) == [
        "employment_offer_letter",
        "position_details",
        "compensation_and_benefits",
    ]


def test_extract_predicted_order_handles_dictionary_section_names():
    evaluator = TemplateEvaluator()
    prediction = {
        "sections": [
            {"title_or_pattern": "Employment Offer Letter"},
            {"section_name": "Position Details"},
            {"name": "Compensation and Benefits"},
            {"title": "Acceptance"},
        ]
    }

    assert evaluator._extract_predicted_order(prediction) == [
        "employment_offer_letter",
        "position_details",
        "compensation_and_benefits",
        "acceptance",
    ]


def test_extract_predicted_variables_handles_real_variable_field_objects():
    """Test that real VariableField objects are extracted correctly."""
    from superdocs_template_inference.template_inference.result import VariableField

    evaluator = TemplateEvaluator()
    prediction = {
        "variables": [
            VariableField(
                variable_name="department",
                semantic_role="organization_unit",
                section_context="position_details",
                inferred_type="string",
            ),
            VariableField(
                variable_name="employment_type",
                semantic_role="employment_classification",
                section_context="conditions_of_employment",
                inferred_type="enum",
                enum_values=["Full-time", "Part-time", "Contract"],
            ),
        ]
    }

    extracted = evaluator._extract_predicted_variables(prediction)

    # Verify extraction succeeded
    assert len(extracted) == 2
    assert extracted[0] == {"variable_name": "department", "inferred_type": "string"}
    assert extracted[1] == {"variable_name": "employment_type", "inferred_type": "enum"}
    # Verify we got the actual variable name, not string representation
    assert "VariableField(" not in extracted[0]["variable_name"]
    assert "VariableField(" not in extracted[1]["variable_name"]


def test_extract_predicted_variables_handles_fallback_name_type_attributes():
    """Test that objects with name/type attributes (fallback) work correctly."""
    evaluator = TemplateEvaluator()

    # Create a simple object with name and type attributes
    class SimpleFieldObject:
        def __init__(self, name, typ):
            self.name = name
            self.type = typ

    prediction = {
        "variables": [
            SimpleFieldObject("candidate_name", "string"),
            SimpleFieldObject("annual_ctc", "currency"),
        ]
    }

    extracted = evaluator._extract_predicted_variables(prediction)

    # Verify extraction used fallback attributes
    assert len(extracted) == 2
    assert extracted[0] == {"variable_name": "candidate_name", "inferred_type": "string"}
    assert extracted[1] == {"variable_name": "annual_ctc", "inferred_type": "currency"}


def test_extract_predicted_variables_preserves_dictionary_handling():
    """Test that existing dictionary-backed variables still work."""
    evaluator = TemplateEvaluator()
    prediction = {
        "variables": [
            {"variable_name": "job_title", "inferred_type": "string"},
            {"variable_name": "salary", "inferred_type": "currency"},
            {"name": "bonus", "type": "currency"},  # fallback in dict
        ]
    }

    extracted = evaluator._extract_predicted_variables(prediction)

    assert len(extracted) == 3
    assert extracted[0] == {"variable_name": "job_title", "inferred_type": "string"}
    assert extracted[1] == {"variable_name": "salary", "inferred_type": "currency"}
    assert extracted[2] == {"variable_name": "bonus", "inferred_type": "currency"}
