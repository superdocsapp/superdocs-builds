from __future__ import annotations

from uuid import uuid4

from app.engines.conflicts import build_clusters, detect_conflicts, normalize_label
from app.schemas.domain import Citation, Fact, FactType

DOC_A = uuid4()
DOC_B = uuid4()


def money_fact(label: str, amount: float, doc, currency: str = "USD") -> Fact:
    return Fact(
        document_id=doc,
        fact_type=FactType.CURRENCY,
        label=label,
        raw_value=f"{currency} {amount:,.2f}",
        normalized_value={"amount": amount, "currency": currency},
        citation=Citation(document_id=doc, page=1, quote=str(amount)),
    )


def test_normalize_label_ignores_stopwords_and_order():
    assert normalize_label("Total Contract Value") == normalize_label("contract value")


def test_cross_document_numeric_conflict_detected():
    facts = [
        money_fact("Contract Value", 100_000, DOC_A),
        money_fact("contract value", 120_000, DOC_B),
    ]
    findings = detect_conflicts(facts, cross_document_only=True)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.finding_type == "numeric_conflict"
    assert finding.severity == "critical"
    assert len(finding.citations) == 2
    assert "across documents" in finding.explanation


def test_matching_values_do_not_conflict():
    facts = [money_fact("Contract Value", 100_000, DOC_A), money_fact("Contract Value", 100_000, DOC_B)]
    assert detect_conflicts(facts) == []


def test_currency_mismatch_reported_separately():
    facts = [
        money_fact("Fee", 1000, DOC_A, currency="USD"),
        money_fact("Fee", 1000, DOC_B, currency="EUR"),
    ]
    findings = detect_conflicts(facts)
    assert [f.finding_type for f in findings] == ["currency_mismatch"]


def test_date_conflict_across_documents():
    facts = [
        Fact(
            document_id=doc,
            fact_type=FactType.DATE,
            label="Effective Date",
            raw_value=iso,
            normalized_value={"iso_date": iso},
            citation=Citation(document_id=doc, page=1, quote=iso),
        )
        for doc, iso in ((DOC_A, "2025-01-01"), (DOC_B, "2025-02-01"))
    ]
    findings = detect_conflicts(facts, cross_document_only=True)
    assert findings[0].finding_type == "date_conflict"
    assert findings[0].difference == "31 days"


def test_entity_conflict_on_invoice_number():
    facts = [
        Fact(
            document_id=doc,
            fact_type=FactType.INVOICE_NUMBER,
            label="Invoice Number",
            raw_value=value,
            citation=Citation(document_id=doc, page=1, quote=value),
        )
        for doc, value in ((DOC_A, "INV-1001"), (DOC_B, "INV-1002"))
    ]
    findings = detect_conflicts(facts)
    assert findings[0].finding_type == "entity_conflict"
    assert findings[0].severity == "high"


def test_cross_document_only_filters_intra_document_pairs():
    facts = [money_fact("Total", 10, DOC_A), money_fact("Total", 20, DOC_A)]
    assert detect_conflicts(facts, cross_document_only=True) == []
    assert detect_conflicts(facts, cross_document_only=False)


def test_clusters_group_by_type_and_label():
    clusters = build_clusters([money_fact("Total", 1, DOC_A), money_fact("total", 2, DOC_B)])
    assert len(clusters) == 1 and len(clusters[0].facts) == 2
    assert clusters[0].cross_document
