"""Tests for memo grounding validation."""

import pytest
from backend.modules.tariff.memo_grounding import (
    MemoGroundingValidator,
    validate_memo_sections,
    GroundingViolation,
)
from backend.modules.tariff.memo_types import (
    ProductFacts,
    RulingFacts,
    MemoSectionOutput,
    Recommendation,
)


def test_placeholder_detection():
    """Placeholder text should be detected."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="The product is [PLACEHOLDER] material",
        analyst_reasoning="TODO: Add reasoning",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="product_description",
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    placeholder_violations = [v for v in violations if v.category == "placeholder_content"]
    assert len(placeholder_violations) >= 1
    assert any("PLACEHOLDER" in v.message or "TODO" in v.message for v in placeholder_violations)


def test_product_fact_consistency_pass():
    """Valid product material should pass."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="Widget",
        material_composition="aluminum alloy",
    )
    section = MemoSectionOutput(
        content="The product is made of aluminum alloy",
        analyst_reasoning="Material confirmed from specification",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) == 0


def test_product_fact_consistency_fail():
    """Conflicting material should be detected."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="Widget",
        material_composition="aluminum",
    )
    section = MemoSectionOutput(
        content="The product is made of plastic polymer",
        analyst_reasoning="Material analysis",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) >= 1
    assert "plastic" in material_conflicts[0].message.lower()
    assert "aluminum" in material_conflicts[0].message.lower()


def test_invalid_ruling_reference():
    """Fabricated ruling number should be detected."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="HQ H265674",
            applicable_classification="7326.90.8588",
        )
    ]
    section = MemoSectionOutput(
        content="According to ruling HQ H999999, classification is 1234.56.7890",
        analyst_reasoning="Analysis",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) >= 1
    assert "HQ H999999" in invalid_rulings[0].message


def test_valid_ruling_reference():
    """Valid ruling reference should pass."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="HQ H265674",
            applicable_classification="7326.90.8588",
        )
    ]
    section = MemoSectionOutput(
        content="According to ruling HQ H265674, classification is 7326.90.8588",
        analyst_reasoning="Analysis",
        source_attribution=[{"ruling": "HQ H265674"}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0


def test_unsupported_no_ruling_statement():
    """'No ruling' claim when rulings exist should fail."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="HQ H265674",
            document_id="ruling-1",
        )
    ]
    section = MemoSectionOutput(
        content="No previous rulings exist for this product type",
        analyst_reasoning="Analysis",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    unsupported = [v for v in violations if v.category == "unsupported_claim"]
    assert len(unsupported) >= 1
    assert "no ruling" in unsupported[0].message.lower()
    assert "matched ruling" in unsupported[0].message.lower()


def test_supported_no_ruling_statement():
    """'No ruling' claim when no rulings exist should pass."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="No relevant classification ruling was identified in the supplied workspace documents",
        analyst_reasoning="Analysis",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    unsupported = [v for v in violations if v.category == "unsupported_claim"]
    assert len(unsupported) == 0


def test_recommendation_placeholder_hs_code():
    """Placeholder HS code in recommendation should fail."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="Recommendation",
        analyst_reasoning="Analysis",
        source_attribution=[],
        recommendation=Recommendation(
            hs_code="XXXX.XX.XXXX",
            description="Placeholder",
            reasoning="TBD",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    classification_errors = [v for v in violations if v.category == "unsupported_classification"]
    assert len(classification_errors) >= 1
    assert "placeholder" in classification_errors[0].message.lower()


def test_recommendation_valid_hs_code():
    """Valid HS code with proper reasoning should pass."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="Recommendation",
        analyst_reasoning="Analysis",
        source_attribution=[{"source": "ruling HQ H265674"}],
        recommendation=Recommendation(
            hs_code="7326.90.8588",
            description="Other articles of iron or steel",
            reasoning="Based on material composition (aluminum) and intended use as storage container",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=ProductFacts(material_composition="aluminum"),
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    classification_errors = [v for v in violations if v.category == "unsupported_classification"]
    assert len(classification_errors) == 0


def test_recommendation_missing_reasoning():
    """Recommendation with insufficient reasoning should fail."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="Recommendation",
        analyst_reasoning="Analysis",
        source_attribution=[],
        recommendation=Recommendation(
            hs_code="7326.90.8588",
            description="Classification",
            reasoning="",  # Empty reasoning
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    missing_source = [v for v in violations if v.category == "missing_source"]
    assert len(missing_source) >= 1
    assert "reasoning" in missing_source[0].message.lower()


def test_recommendation_without_ruling_reference():
    """Recommendation without ruling reference when rulings exist should warn."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="Recommendation",
        analyst_reasoning="Analysis",
        source_attribution=[],
        recommendation=Recommendation(
            hs_code="7326.90.8588",
            description="Classification",
            reasoning="Based on material composition and product characteristics, appropriate classification.",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=None,
        ruling_facts=[RulingFacts(ruling_number="HQ H265674", document_id="ruling-1")],
        matched_ruling_ids=["ruling-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    warnings = [v for v in violations if v.severity == "warning"]
    assert len(warnings) >= 1
    assert any("matched ruling" in w.message.lower() for w in warnings)


def test_missing_source_attribution():
    """Missing source attribution in required section should warn."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="Analysis of relevant rulings",
        analyst_reasoning="Detailed analysis",
        source_attribution=[],  # Empty
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",  # Requires attribution
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    missing_source = [v for v in violations if v.category == "missing_source"]
    assert len(missing_source) >= 1


def test_multiple_violations():
    """Multiple violations should all be detected."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(material_composition="aluminum")
    section = MemoSectionOutput(
        content="The plastic product has [PLACEHOLDER] characteristics",
        analyst_reasoning="TODO: Complete this section",
        source_attribution=[],
        recommendation=Recommendation(
            hs_code="XXXX.XX",
            description="TBD",
            reasoning="",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    # Should detect: placeholder, material conflict, invalid HS code, missing reasoning
    assert len(violations) >= 3

    categories = {v.category for v in violations}
    assert "placeholder_content" in categories
    assert "product_fact_conflict" in categories or "unsupported_classification" in categories


def test_validate_memo_sections_integration():
    """Integration test for validate_memo_sections function."""
    product_facts = ProductFacts(
        product_name="Storage Container",
        material_composition="aluminum",
    )
    ruling_facts = [
        RulingFacts(
            ruling_number="HQ H265674",
            applicable_classification="7326.90.8588",
            document_id="ruling-1",
        )
    ]
    memo_sections = {
        "product_description": MemoSectionOutput(
            content="Aluminum storage container",
            analyst_reasoning="Material verified",
            source_attribution=[{"source": "specification"}],
        ),
        "recommended_classification": MemoSectionOutput(
            content="Recommendation",
            analyst_reasoning="Analysis",
            source_attribution=[{"source": "ruling HQ H265674"}],
            recommendation=Recommendation(
                hs_code="7326.90.8588",
                description="Classification",
                reasoning="Based on ruling HQ H265674 for similar aluminum products",
            ),
        ),
    }

    violations = validate_memo_sections(
        memo_sections=memo_sections,
        product_facts=product_facts,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    # Should pass with no critical errors
    errors = [v for v in violations if v.severity == "error"]
    assert len(errors) == 0


def test_honest_uncertainty_passes():
    """Honest acknowledgment of uncertainty should not fail."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content=(
            "The product material appears to be aluminum based on available documentation. "
            "However, additional technical specifications would strengthen this determination."
        ),
        analyst_reasoning="Analysis notes limitations",
        source_attribution=[{"source": "product specification", "page": 1}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=ProductFacts(material_composition="aluminum"),
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    # Honest uncertainty should not trigger errors
    errors = [v for v in violations if v.severity == "error"]
    assert len(errors) == 0


def test_unrelated_ruling_not_enforced():
    """Unmatched rulings should not enforce classification."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="HQ H999999",
            applicable_classification="1234.56.7890",
            document_id="ruling-2",  # Different document
        )
    ]
    section = MemoSectionOutput(
        content="Product classified as 7326.90.8588",
        analyst_reasoning="Based on product characteristics",
        source_attribution=[],
        recommendation=Recommendation(
            hs_code="7326.90.8588",
            description="Classification",
            reasoning="Material and construction analysis",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=[],  # Ruling not matched
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    # Should not enforce unmatched ruling classification
    errors = [v for v in violations if v.category == "ruling_conflict" and v.severity == "error"]
    assert len(errors) == 0


def test_meta_ai_language_detection():
    """Prohibited internal meta AI phrases should trigger warnings."""
    validator = MemoGroundingValidator()
    section = MemoSectionOutput(
        content="This section is drafted to establish the product identity. The description focuses on mechanics.",
        analyst_reasoning="Full material analysis has been excluded to adhere to section focus requirements.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="product_description",
        product_facts=None,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    meta_violations = [v for v in violations if v.category == "meta_ai_language"]
    assert len(meta_violations) >= 2
    assert any("This section is drafted" in v.message for v in meta_violations)
    assert any("has been excluded to adhere to" in v.message for v in meta_violations)


def test_sanitize_memo_text_removes_meta_phrases_and_orphan_headings():
    """sanitize_memo_text must strip meta AI boilerplate and orphan reasoning headings."""
    from backend.modules.tariff.memo_grounding import sanitize_memo_text

    raw_content = (
        "This section is drafted to establish the commercial identity.\n"
        "The AeroLink X7 is an unmanned aerial vehicle (UAV) designed for industrial inspection.\n"
        "The description focuses on the physical form."
    )
    raw_reasoning = "Reasoning:\nFull material analysis has been excluded to adhere to section focus requirements."

    clean_content, clean_reasoning = sanitize_memo_text(raw_content, raw_reasoning)

    assert "This section is drafted" not in clean_content
    assert "The description focuses" not in clean_content
    assert "AeroLink X7 is an unmanned aerial vehicle" in clean_content
    assert "Reasoning:" not in clean_reasoning
    assert "excluded to adhere to" not in clean_reasoning


def test_sanitize_memo_text_suppresses_duplicate_reasoning():
    """When analyst_reasoning is identical to content or empty after cleaning, it is cleared."""
    from backend.modules.tariff.memo_grounding import sanitize_memo_text

    raw_content = "Classified under heading 8806 as an unmanned aircraft."
    raw_reasoning = "Classified under heading 8806 as an unmanned aircraft."

    clean_content, clean_reasoning = sanitize_memo_text(raw_content, raw_reasoning)
    assert clean_content == "Classified under heading 8806 as an unmanned aircraft."
    assert clean_reasoning == ""


def test_material_substring_word_boundary_no_false_positive():
    """Words like 'environmental' containing 'iron' should not trigger material conflict."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="Hub",
        material_composition="PC/ABS polymer with metal shielding",
    )
    section = MemoSectionOutput(
        content="The unit is designed for industrial or facility-level environmental stability.",
        analyst_reasoning="Environmental durability considerations.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="technical_characteristics",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) == 0


def test_material_word_boundary_detects_real_conflict():
    """Explicit mention of unlisted material like 'cast iron' should trigger material conflict."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="Hub",
        material_composition="aluminum",
    )
    section = MemoSectionOutput(
        content="The housing is constructed from cast iron frames.",
        analyst_reasoning="Iron provides rigidity.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) >= 1
    assert "iron" in material_conflicts[0].message.lower()


def test_custom_ruling_format_reference():
    """National/custom ruling numbers like NCR-THM-2026-0417 should be recognized."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="9031.80.40",
            document_id="ruling-doc-1",
        )
    ]
    section = MemoSectionOutput(
        content="Precedent established in ruling NCR-THM-2026-0417 for monitoring units.",
        analyst_reasoning="Distinguished from NCR-THM-2026-0417.",
        source_attribution=[{"ruling": "NCR-THM-2026-0417"}],
        recommendation=Recommendation(
            hs_code="8517.62.00",
            description="Communication apparatus",
            reasoning="Classified under 8517.62.00 distinguishing from NCR-THM-2026-0417.",
        ),
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="recommended_classification",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-doc-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0

    missing_sources = [v for v in violations if v.category == "missing_source"]
    assert len(missing_sources) == 0


def test_product_model_number_not_treated_as_invalid_ruling():
    """Product model numbers like TT-IMU-4 or ALX7-X7-240 should not be falsely treated as invalid rulings."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7 Smart Communication Hub",
        model="ALX7-X7-240",
        material_composition="PC/ABS polymer with metal shielding",
    )
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            product_description="ThermoTrack Industrial Monitoring Unit, Model TT-IMU-4",
            applicable_classification="HTX 9031.80.40",
            document_id="ruling-doc-1",
        )
    ]
    section = MemoSectionOutput(
        content=(
            "In Ruling NCR-THM-2026-0417, the authority examined an industrial monitoring unit "
            "(Model TT-IMU-4) that utilized a processor and network interfaces. The AeroLink X7 "
            "(Model ALX7-X7-240) shares structural features but functions as a communication hub."
        ),
        analyst_reasoning="Distinguished from precedent NCR-THM-2026-0417.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=product_facts,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-doc-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0


def test_fabricated_ruling_number_is_detected():
    """Fabricated/unsupported ruling references must be detected and flagged as errors."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="ruling-doc-1",
        )
    ]
    section = MemoSectionOutput(
        content="Under Ruling NCR-FAKE-2026-9999 and HQ H999999, the item was classified.",
        analyst_reasoning="Precedent NCR-FAKE-2026-9999 applies.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["ruling-doc-1"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) >= 1
    assert any("NCR-FAKE-2026-9999" in v.message or "HQ H999999" in v.message for v in invalid_rulings)


def test_copper_networking_interface_terminology_passes():
    """Copper networking and interface terminology should NOT trigger a material conflict."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7 Smart Communication Hub",
        material_composition="PC/ABS polymer with metal shielding",
        functional_characteristics="Aggregates interfaces; includes dual 1 GbE copper interfaces, Wi-Fi 6",
    )
    section = MemoSectionOutput(
        content="Connectivity is facilitated through dual 1 GbE copper Ethernet interfaces and Wi-Fi 6.",
        analyst_reasoning="The copper port and wireless modules coordinate connected devices.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="technical_characteristics",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) == 0


def test_genuine_unsupported_material_fails():
    """Genuinely unsupported physical material claims should be detected and flagged."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7 Smart Communication Hub",
        material_composition="PC/ABS polymer with metal shielding",
    )
    section = MemoSectionOutput(
        content="The unit is constructed with a solid aluminum housing and steel brackets.",
        analyst_reasoning="The aluminum enclosure provides structural integrity.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    material_conflicts = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(material_conflicts) >= 1
    conflicting_mats = [v.details.get("conflicting_material") for v in material_conflicts]
    assert "aluminum" in conflicting_mats or "steel" in conflicting_mats


def test_ruling_hs_code_prefix_normalization():
    """HTX/HTS/HTSUS prefixes in ruling classification should be normalized and match numeric codes."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="In ruling NCR-THM-2026-0417, the apparatus was determined to fall under 9031.80.40.",
        analyst_reasoning="Distinguished from precedent NCR-THM-2026-0417 classified under 9031.80.40.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    ruling_conflicts = [v for v in violations if v.category == "ruling_conflict"]
    assert len(ruling_conflicts) == 0


def test_genuine_ruling_classification_mismatch_warns():
    """Genuine mismatch between ruling classification and memo discussion should produce a warning."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    # Memo discusses ruling section but mentions completely different HS code without 9031.80.40
    section = MemoSectionOutput(
        content="In ruling NCR-THM-2026-0417, the apparatus was classified under 8517.62.00.",
        analyst_reasoning="Precedent applies under 8517.62.00.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    ruling_conflicts = [v for v in violations if v.category == "ruling_conflict"]
    assert len(ruling_conflicts) >= 1
    assert "9031.80.40" in ruling_conflicts[0].message


def test_ruling_document_uuid_accepted():
    """Known ruling document UUID should be recognized as a valid ruling document reference."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Legal analysis incorporates precedent from Ruling NCR-THM-2026-0417 (Ruling 58a849a5-73cd-4c76-9562-107651bdba29).",
        analyst_reasoning="Citing precedent document 58a849a5-73cd-4c76-9562-107651bdba29.",
        source_attribution=[{"document_id": "58a849a5-73cd-4c76-9562-107651bdba29"}],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="supporting_citations",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0


def test_unknown_ruling_uuid_rejected():
    """Unknown fabricated ruling document UUID should be flagged as invalid reference."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Legal analysis cites Ruling 11111111-2222-3333-4444-555555555555 as controlling precedent.",
        analyst_reasoning="Unknown ruling reference.",
        source_attribution=[],
    )

    violations = validator.validate_section(
        section_output=section,
        section_type="supporting_citations",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) >= 1
    assert "11111111-2222-3333-4444-555555555555" in invalid_rulings[0].message


def test_aerolink_combined_memo_validation_clean_pass():
    """A full AeroLink-style memo containing copper interfaces, ruling citations, and UUID references passes with 0 violations."""
    product_facts = ProductFacts(
        product_name="AeroLink X7 Smart Communication Hub",
        manufacturer="Northstar Connected Devices Ltd.",
        model="ALX7-X7-240",
        material_composition="PC/ABS polymer with metal shielding",
        functional_characteristics="Aggregates wired/wireless communication interfaces and coordinates connected devices; includes 4-core ARM-based processor, 4 GB LPDDR4 memory, 128 GB eMMC/flash storage, dual 1 GbE copper interfaces, Wi-Fi 6, and Bluetooth Low Energy",
    )
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            product_description="ThermoTrack Industrial Monitoring Unit, Model TT-IMU-4",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    matched_ruling_ids = ["58a849a5-73cd-4c76-9562-107651bdba29"]

    memo_sections = {
        "product_overview": MemoSectionOutput(
            content="The AeroLink X7 (Model ALX7-X7-240) is housed in PC/ABS polymer with metal shielding and features dual 1 GbE copper Ethernet interfaces.",
            analyst_reasoning="Enclosure and interface specifications confirmed.",
            source_attribution=[{"source": "product spec"}],
        ),
        "relevant_previous_rulings": MemoSectionOutput(
            content="In Ruling NCR-THM-2026-0417, the ThermoTrack unit (Model TT-IMU-4) was classified under 9031.80.40. AeroLink X7 differs functionally.",
            analyst_reasoning="Distinguished from NCR-THM-2026-0417.",
            source_attribution=[{"ruling": "NCR-THM-2026-0417"}],
        ),
        "supporting_citations": MemoSectionOutput(
            content="Citations include product specifications and Ruling NCR-THM-2026-0417 (Ruling 58a849a5-73cd-4c76-9562-107651bdba29).",
            analyst_reasoning="All sources verified.",
            source_attribution=[{"document_id": "58a849a5-73cd-4c76-9562-107651bdba29"}],
        ),
    }

    violations = validate_memo_sections(
        memo_sections=memo_sections,
        product_facts=product_facts,
        ruling_facts=ruling_facts,
        matched_ruling_ids=matched_ruling_ids,
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )

    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]

    assert len(errors) == 0, f"Expected 0 errors, got: {[e.to_dict() for e in errors]}"
    assert len(warnings) == 0, f"Expected 0 warnings, got: {[w.to_dict() for w in warnings]}"


def test_regression_a_pc_abs_polymer_with_metal_shielding_valid():
    """A. 'PC/ABS polymer with metal shielding' is valid."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7",
        material_composition="PC/ABS polymer with metal shielding",
    )
    section = MemoSectionOutput(
        content="The housing is constructed from PC/ABS polymer with internal metal shielding.",
        analyst_reasoning="Material matches authoritative specification.",
        source_attribution=[],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    errors = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(errors) == 0


def test_regression_b_dual_copper_ethernet_interfaces_no_conflict():
    """B. 'dual 1 GbE copper Ethernet interfaces' does NOT trigger a material conflict."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7",
        material_composition="PC/ABS polymer with metal shielding",
        functional_characteristics="dual 1 GbE copper interfaces",
    )
    section = MemoSectionOutput(
        content="The device provides connectivity via dual 1 GbE copper Ethernet interfaces.",
        analyst_reasoning="Interface description matching functional characteristics.",
        source_attribution=[],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="technical_characteristics",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    errors = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(errors) == 0


def test_regression_c_unsupported_aluminum_enclosure_triggers_conflict():
    """C. A genuinely unsupported material such as 'aluminum enclosure' still triggers a conflict when unsupported."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="AeroLink X7",
        material_composition="PC/ABS polymer with metal shielding",
    )
    section = MemoSectionOutput(
        content="The unit features an aluminum enclosure designed for thermal dissipation.",
        analyst_reasoning="Aluminum enclosure provides ruggedness.",
        source_attribution=[],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="material_composition",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    errors = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(errors) >= 1
    assert "aluminum" in errors[0].message.lower()


def test_regression_d_functional_terminology_containing_material_words_valid():
    """D. Other legitimate functional terminology containing material words is not incorrectly classified as physical material."""
    validator = MemoGroundingValidator()
    product_facts = ProductFacts(
        product_name="Smart Switch",
        material_composition="polycarbonate",
        functional_characteristics="fiberglass PCB with copper traces and gold contacts",
        construction="injection molded casing with internal PCB assembly",
    )
    section = MemoSectionOutput(
        content="The module integrates copper traces on a printed circuit board with copper port connections.",
        analyst_reasoning="Internal electrical characteristics verified from construction data.",
        source_attribution=[],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="technical_characteristics",
        product_facts=product_facts,
        ruling_facts=[],
        matched_ruling_ids=[],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    errors = [v for v in violations if v.category == "product_fact_conflict"]
    assert len(errors) == 0


def test_regression_e_htx_prefixed_ruling_code_normalization():
    """E. HTX 9031.80.40 and 9031.80.40 must compare equal."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Precedent NCR-THM-2026-0417 classified goods under 9031.80.40.",
        analyst_reasoning="Discussion of 9031.80.40 precedent.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    ruling_conflicts = [v for v in violations if v.category == "ruling_conflict"]
    assert len(ruling_conflicts) == 0


def test_regression_f_genuine_mismatched_ruling_code_triggers_conflict():
    """F. Authoritative HTX 9031.80.40 vs Memo 8517.62.00 must still trigger ruling_conflict."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Under ruling NCR-THM-2026-0417, the item was classified under 8517.62.00.",
        analyst_reasoning="Ruling precedent analysis under 8517.62.00.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    ruling_conflicts = [v for v in violations if v.category == "ruling_conflict"]
    assert len(ruling_conflicts) >= 1
    assert "9031.80.40" in ruling_conflicts[0].message


def test_regression_g_known_ruling_document_uuid_accepted():
    """G. Known ruling document UUID must be accepted when it matches ruling_facts.document_id."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Ruling 58a849a5-73cd-4c76-9562-107651bdba29 provides precedent.",
        analyst_reasoning="Citing document ID.",
        source_attribution=[{"document_id": "58a849a5-73cd-4c76-9562-107651bdba29"}],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="supporting_citations",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0


def test_regression_h_known_ruling_number_accepted():
    """H. Known ruling number NCR-THM-2026-0417 must be accepted."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="Ruling NCR-THM-2026-0417 was evaluated during classification.",
        analyst_reasoning="Evaluation of NCR-THM-2026-0417.",
        source_attribution=[{"ruling_number": "NCR-THM-2026-0417"}],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) == 0


def test_regression_i_unknown_fabricated_ruling_identifier_rejected():
    """I. Unknown fabricated ruling identifier NCR-FAKE-9999 must still be rejected."""
    validator = MemoGroundingValidator()
    ruling_facts = [
        RulingFacts(
            ruling_number="NCR-THM-2026-0417",
            applicable_classification="HTX 9031.80.40",
            document_id="58a849a5-73cd-4c76-9562-107651bdba29",
        )
    ]
    section = MemoSectionOutput(
        content="According to Ruling NCR-FAKE-9999, the item is classified under heading 8517.",
        analyst_reasoning="Fabricated ruling cite.",
        source_attribution=[],
    )
    violations = validator.validate_section(
        section_output=section,
        section_type="relevant_previous_rulings",
        product_facts=None,
        ruling_facts=ruling_facts,
        matched_ruling_ids=["58a849a5-73cd-4c76-9562-107651bdba29"],
        reconciliation_conflicts=[],
        retrieved_evidence=[],
    )
    invalid_rulings = [v for v in violations if v.category == "invalid_ruling_reference"]
    assert len(invalid_rulings) >= 1
    assert "NCR-FAKE-9999" in invalid_rulings[0].message




