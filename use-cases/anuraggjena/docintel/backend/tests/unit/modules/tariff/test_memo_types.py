import pytest

from backend.modules.tariff.memo_types import (
    GENERATION_ORDER,
    AlternativeClassification,
    MemoSectionType,
    ProductFacts,
    RulingFacts,
    RulingQuotation,
    SECTION_ORDER,
    SourceLocation,
)


def test_section_order_has_14_entries():
    assert len(SECTION_ORDER) == 14
    assert SECTION_ORDER[0].section_type == MemoSectionType.EXECUTIVE_SUMMARY
    assert SECTION_ORDER[-1].section_type == MemoSectionType.REVIEWER_NOTES


def test_section_order_is_deterministic():
    orders = [s.section_order for s in SECTION_ORDER]
    assert orders == list(range(1, 15))


def test_invalid_section_type_rejected():
    with pytest.raises(ValueError):
        MemoSectionType("nonexistent_section")


def test_product_facts_allows_empty_fields():
    facts = ProductFacts()
    assert facts.product_name is None
    assert facts.source_locations == []


def test_ruling_facts_requires_grounded_quotations():
    ruling = RulingFacts(
        ruling_number="HQ-123456",
        issuing_authority="US CBP",
        quotations=[RulingQuotation(text="The product is classified...", page=2)],
    )
    assert ruling.ruling_number == "HQ-123456"


def test_alternative_classification_structure():
    alt = AlternativeClassification(
        candidate_hs="8471.30",
        description="Automatic data processing machine",
        supporting_arguments="Has CPU and memory",
        rejection_reason="Lacks computing capability",
        confidence="medium",
    )
    assert alt.candidate_hs == "8471.30"


def test_generation_order_executive_summary_last():
    assert GENERATION_ORDER[-1] == MemoSectionType.EXECUTIVE_SUMMARY
    assert MemoSectionType.EXECUTIVE_SUMMARY not in GENERATION_ORDER[:-1]


def test_source_location_page_coercion_int():
    """Integer page values pass through unchanged."""
    loc = SourceLocation(document_id="doc1", page=3)
    assert loc.page == 3


def test_source_location_page_coercion_numeric_string():
    """Numeric strings like '3' become integers."""
    loc = SourceLocation(document_id="doc1", page="5")
    assert loc.page == 5


def test_source_location_page_coercion_null():
    """Null/None remains None."""
    loc = SourceLocation(document_id="doc1", page=None)
    assert loc.page is None


def test_source_location_page_coercion_unknown():
    """'unknown' becomes None."""
    loc = SourceLocation(document_id="doc1", page="unknown")
    assert loc.page is None


def test_source_location_page_coercion_empty():
    """Empty string becomes None."""
    loc = SourceLocation(document_id="doc1", page="")
    assert loc.page is None


def test_source_location_page_coercion_na():
    """'n/a' becomes None."""
    loc = SourceLocation(document_id="doc1", page="N/A")
    assert loc.page is None


def test_source_location_page_coercion_invalid():
    """Non-numeric strings become None."""
    loc = SourceLocation(document_id="doc1", page="page three")
    assert loc.page is None


def test_ruling_quotation_page_coercion():
    """RulingQuotation page field uses same normalization."""
    quote = RulingQuotation(text="Classification is clear", page="7")
    assert quote.page == 7

    quote2 = RulingQuotation(text="No page info", page="unknown")
    assert quote2.page is None
