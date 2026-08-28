"""Extractor registry mapping document type labels to extractor classes.

This module provides the central dispatch point for type-specific extraction.
The pipeline's extract_claims node uses this registry to select the appropriate
extractor based on the document's classification label.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.pipeline.extractors.base import FactExtractor
from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor
from src.pipeline.extractors.modification import ModificationExtractor
from src.pipeline.extractors.repayment import RepaymentExtractor

if TYPE_CHECKING:
    pass

# Registry mapping classification labels to their extractor classes.
EXTRACTOR_REGISTRY: dict[str, type[FactExtractor]] = {
    "loan_agreement": LoanAgreementExtractor,
    "modification_agreement": ModificationExtractor,
    "repayment_statement": RepaymentExtractor,
}
