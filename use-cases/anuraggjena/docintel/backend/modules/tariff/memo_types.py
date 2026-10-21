from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class MemoSectionType(str, Enum):
    EXECUTIVE_SUMMARY = "executive_summary"
    PRODUCT_OVERVIEW = "product_overview"
    PRODUCT_DESCRIPTION = "product_description"
    TECHNICAL_CHARACTERISTICS = "technical_characteristics"
    MATERIAL_COMPOSITION = "material_composition"
    PRODUCT_IMAGES = "product_images"
    APPLICABLE_CLASSIFICATION_RULES = "applicable_classification_rules"
    RELEVANT_PREVIOUS_RULINGS = "relevant_previous_rulings"
    CLASSIFICATION_ANALYSIS = "classification_analysis"
    ALTERNATIVES_CONSIDERED = "alternatives_considered"
    ALTERNATIVES_REJECTED = "alternatives_rejected"
    RECOMMENDED_CLASSIFICATION = "recommended_classification"
    SUPPORTING_CITATIONS = "supporting_citations"
    REVIEWER_NOTES = "reviewer_notes"


SECTION_TITLES: Dict[MemoSectionType, str] = {
    MemoSectionType.EXECUTIVE_SUMMARY: "Executive Summary",
    MemoSectionType.PRODUCT_OVERVIEW: "Product Overview",
    MemoSectionType.PRODUCT_DESCRIPTION: "Product Description",
    MemoSectionType.TECHNICAL_CHARACTERISTICS: "Technical Characteristics",
    MemoSectionType.MATERIAL_COMPOSITION: "Material / Physical Composition",
    MemoSectionType.PRODUCT_IMAGES: "Product Images",
    MemoSectionType.APPLICABLE_CLASSIFICATION_RULES: "Applicable Classification Rules",
    MemoSectionType.RELEVANT_PREVIOUS_RULINGS: "Relevant Previous Rulings",
    MemoSectionType.CLASSIFICATION_ANALYSIS: "Classification Analysis",
    MemoSectionType.ALTERNATIVES_CONSIDERED: "Alternative Classifications Considered",
    MemoSectionType.ALTERNATIVES_REJECTED: "Reasons for Rejecting Alternatives",
    MemoSectionType.SUPPORTING_CITATIONS: "Supporting Citations / Sources & Evidence",
    MemoSectionType.RECOMMENDED_CLASSIFICATION: "Final Recommended Classification",
    MemoSectionType.REVIEWER_NOTES: "Reviewer Notes",
}


class SectionOrderEntry(BaseModel):
    section_type: MemoSectionType
    section_order: int
    required: bool = True
    conditional: bool = False


SECTION_ORDER: List[SectionOrderEntry] = [
    SectionOrderEntry(section_type=MemoSectionType.EXECUTIVE_SUMMARY, section_order=1),
    SectionOrderEntry(section_type=MemoSectionType.PRODUCT_OVERVIEW, section_order=2),
    SectionOrderEntry(section_type=MemoSectionType.PRODUCT_DESCRIPTION, section_order=3),
    SectionOrderEntry(section_type=MemoSectionType.TECHNICAL_CHARACTERISTICS, section_order=4),
    SectionOrderEntry(section_type=MemoSectionType.MATERIAL_COMPOSITION, section_order=5),
    SectionOrderEntry(section_type=MemoSectionType.PRODUCT_IMAGES, section_order=6, conditional=True),
    SectionOrderEntry(section_type=MemoSectionType.APPLICABLE_CLASSIFICATION_RULES, section_order=7),
    SectionOrderEntry(section_type=MemoSectionType.RELEVANT_PREVIOUS_RULINGS, section_order=8, conditional=True),
    SectionOrderEntry(section_type=MemoSectionType.CLASSIFICATION_ANALYSIS, section_order=9),
    SectionOrderEntry(section_type=MemoSectionType.ALTERNATIVES_CONSIDERED, section_order=10),
    SectionOrderEntry(section_type=MemoSectionType.ALTERNATIVES_REJECTED, section_order=11),
    SectionOrderEntry(section_type=MemoSectionType.SUPPORTING_CITATIONS, section_order=12),
    SectionOrderEntry(section_type=MemoSectionType.RECOMMENDED_CLASSIFICATION, section_order=13),
    SectionOrderEntry(section_type=MemoSectionType.REVIEWER_NOTES, section_order=14, required=False),
]

GENERATION_ORDER: List[MemoSectionType] = [
    entry.section_type
    for entry in SECTION_ORDER
    if entry.section_type != MemoSectionType.EXECUTIVE_SUMMARY
] + [MemoSectionType.EXECUTIVE_SUMMARY]


class SourceLocation(BaseModel):
    document_id: Optional[str] = None
    page: Optional[int] = None
    excerpt: Optional[str] = None

    @field_validator("page", mode="before")
    @classmethod
    def coerce_page_value(cls, v):
        """
        Normalize page values from LLM output.

        - int → int
        - numeric string "3" → 3
        - null → None
        - "unknown", empty string, or other non-numeric → None

        Never fabricates page numbers.
        """
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() in ("unknown", "n/a", "none"):
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None
        return None


class ProductFacts(BaseModel):
    product_name: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    material_composition: Optional[str] = None
    dimensions: Optional[str] = None
    weight: Optional[str] = None
    construction: Optional[str] = None
    intended_use: Optional[str] = None
    packaging: Optional[str] = None
    manufacturing_process: Optional[str] = None
    physical_characteristics: Optional[str] = None
    functional_characteristics: Optional[str] = None
    source_locations: List[SourceLocation] = Field(default_factory=list)


class RulingQuotation(BaseModel):
    text: str
    page: Optional[int] = None

    @field_validator("page", mode="before")
    @classmethod
    def coerce_page_value(cls, v):
        """Normalize page values (same logic as SourceLocation)."""
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() in ("unknown", "n/a", "none"):
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None
        return None


class RulingFacts(BaseModel):
    ruling_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    product_description: Optional[str] = None
    applicable_classification: Optional[str] = None
    reasoning: Optional[str] = None
    quotations: List[RulingQuotation] = Field(default_factory=list)
    gri_references: List[str] = Field(default_factory=list)
    exceptions: List[str] = Field(default_factory=list)
    source_locations: List[SourceLocation] = Field(default_factory=list)
    document_id: Optional[str] = None


class RulingFactsList(BaseModel):
    rulings: List[RulingFacts] = Field(default_factory=list)


class AlternativeClassification(BaseModel):
    candidate_hs: str
    description: str
    supporting_arguments: str
    rejection_reason: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    confidence: Optional[str] = None


class Recommendation(BaseModel):
    hs_code: str
    description: str
    duty_rate: Optional[str] = None
    reasoning: str
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    confidence: Optional[str] = None
    alternatives_considered: List[str] = Field(default_factory=list)
    unresolved_issues: List[str] = Field(default_factory=list)


class MemoSectionOutput(BaseModel):
    """LLM structured output for a single memo section."""

    content: str
    analyst_reasoning: str
    source_attribution: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: Optional[str] = None
    alternatives: List[AlternativeClassification] = Field(default_factory=list)
    recommendation: Optional[Recommendation] = None
    adopted_knowledge_entry_ids: List[str] = Field(default_factory=list)
