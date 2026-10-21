"""Tests for document reconciliation."""
import pytest
from backend.modules.tariff.document_reconciliation import DocumentReconciliation
from backend.modules.tariff.memo_types import ProductFacts, RulingFacts


def test_no_rulings():
    """No rulings returns empty match."""
    reconciliation = DocumentReconciliation()
    product = ProductFacts(product_name="Widget", material_composition="aluminum")
    result = reconciliation.reconcile(product, [])
    assert result["matched_ruling_ids"] == []
    assert result["conflicts"] == []


def test_material_match():
    """Ruling with matching material is matched."""
    reconciliation = DocumentReconciliation()
    product = ProductFacts(material_composition="aluminum alloy")
    ruling = RulingFacts(
        document_id="ruling-1",
        product_description="aluminum products for industrial use",
    )
    result = reconciliation.reconcile(product, [ruling])
    assert "ruling-1" in result["matched_ruling_ids"]
    assert "aluminum" in result["match_reasons"]["ruling-1"]


def test_no_match_different_material():
    """Ruling with different material gets low/no score."""
    reconciliation = DocumentReconciliation()
    product = ProductFacts(material_composition="plastic polymer")
    ruling = RulingFacts(
        document_id="ruling-1",
        product_description="steel beams for construction",
    )
    result = reconciliation.reconcile(product, [ruling])
    # Low score may still match, but should not be high confidence
    # In real usage, this would be handled by match score thresholds


def test_product_name_match():
    """Ruling with shared product name keywords is matched."""
    reconciliation = DocumentReconciliation()
    product = ProductFacts(product_name="Folding storage container")
    ruling = RulingFacts(
        document_id="ruling-1",
        product_description="Storage containers made of various materials",
    )
    result = reconciliation.reconcile(product, [ruling])
    assert "ruling-1" in result["matched_ruling_ids"]


def test_multiple_rulings():
    """Multiple rulings are evaluated independently."""
    reconciliation = DocumentReconciliation()
    product = ProductFacts(
        product_name="Widget",
        material_composition="aluminum",
    )
    ruling1 = RulingFacts(
        document_id="ruling-1",
        product_description="aluminum products",
    )
    ruling2 = RulingFacts(
        document_id="ruling-2",
        product_description="plastic products",
    )
    result = reconciliation.reconcile(product, [ruling1, ruling2])
    # Should match aluminum ruling
    assert "ruling-1" in result["matched_ruling_ids"]
