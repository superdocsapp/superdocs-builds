"""Type-specific extraction strategies for the microfinance pipeline."""

from src.pipeline.extractors.base import ExtractedFact, FactExtractor, SourceSpan
from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor
from src.pipeline.extractors.modification import ModificationExtractor
from src.pipeline.extractors.registry import EXTRACTOR_REGISTRY
from src.pipeline.extractors.repayment import RepaymentExtractor

__all__ = [
    "EXTRACTOR_REGISTRY",
    "ExtractedFact",
    "FactExtractor",
    "LoanAgreementExtractor",
    "ModificationExtractor",
    "RepaymentExtractor",
    "SourceSpan",
]
