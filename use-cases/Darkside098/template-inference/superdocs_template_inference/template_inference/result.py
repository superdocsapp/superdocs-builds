"""Data models for template inference results."""

from dataclasses import dataclass, field


@dataclass
class InferenceEvidence:
    """Evidence for an inference decision."""

    evidence_type: str  # e.g., "repeated_structure", "section_alignment", "value_variance"
    source_document_ids: list[str]
    related_section: str | None = None
    related_variable: str | None = None
    observation: str = ""  # summary of the observation
    confidence_contribution: float = 0.0


@dataclass
class TemplateSection:
    """An inferred section within a template."""

    section_id: str
    title_or_pattern: str
    inferred_type: str  # "REQUIRED", "OPTIONAL", "CONDITIONAL"
    order: int  # 0-based position in the template
    presence_frequency: float  # 0.0–1.0, fraction of documents with this section
    presence_type: str  # "always", "optional", "conditional"
    content_representation: str  # normalized/summary content
    variables: list[str] = field(default_factory=list)  # variable_names in this section
    conditional_info: dict | None = None  # for CONDITIONAL sections
    confidence: float = 1.0
    evidence: list[InferenceEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "section_id": self.section_id,
            "title_or_pattern": self.title_or_pattern,
            "inferred_type": self.inferred_type,
            "order": self.order,
            "presence_frequency": self.presence_frequency,
            "presence_type": self.presence_type,
            "content_representation": self.content_representation,
            "variables": self.variables,
            "conditional_info": self.conditional_info,
            "confidence": self.confidence,
            "evidence": [
                {
                    "evidence_type": e.evidence_type,
                    "source_document_ids": e.source_document_ids,
                    "related_section": e.related_section,
                    "related_variable": e.related_variable,
                    "observation": e.observation,
                    "confidence_contribution": e.confidence_contribution,
                }
                for e in self.evidence
            ],
        }


@dataclass
class VariableField:
    """An inferred variable field within a template."""

    variable_name: str
    semantic_role: str  # e.g., "person_name", "employee_id", "salary", "unknown"
    section_context: str  # section where this variable appears
    observed_values: list[str] = field(default_factory=list)
    frequency: float = 1.0  # 0.0–1.0, fraction of documents with this variable
    confidence: float = 1.0
    evidence: list[InferenceEvidence] = field(default_factory=list)
    # M6 enhancements (optional, for type and metadata inference)
    inferred_type: str | None = None  # string|enum|date|datetime|time|currency|integer|email|phone|boolean
    is_enum: bool = False  # whether values are enumerated from fixed set
    enum_values: list[str] = field(default_factory=list)  # if is_enum=True
    format_pattern: str | None = None  # regex/format pattern if recognized
    unique_per_document: bool = False  # whether value is unique per document

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        result_dict = {
            "variable_name": self.variable_name,
            "semantic_role": self.semantic_role,
            "section_context": self.section_context,
            "observed_values": self.observed_values,
            "frequency": self.frequency,
            "confidence": self.confidence,
            "evidence": [
                {
                    "evidence_type": e.evidence_type,
                    "source_document_ids": e.source_document_ids,
                    "related_section": e.related_section,
                    "related_variable": e.related_variable,
                    "observation": e.observation,
                    "confidence_contribution": e.confidence_contribution,
                }
                for e in self.evidence
            ],
        }
        # Include M6 enhancements if populated
        if self.inferred_type is not None:
            result_dict["inferred_type"] = self.inferred_type
        if self.is_enum:
            result_dict["is_enum"] = self.is_enum
            result_dict["enum_values"] = self.enum_values
        if self.format_pattern is not None:
            result_dict["format_pattern"] = self.format_pattern
        if self.unique_per_document:
            result_dict["unique_per_document"] = self.unique_per_document
        return result_dict


@dataclass
class ConditionalRule:
    """A conditional rule for section presence."""

    target_section: str
    condition: dict  # {"field": "...", "operator": "...", "value": "..."}
    supporting_evidence: list[InferenceEvidence] = field(default_factory=list)
    confidence: float = 1.0
    status: str = "inferred"  # "inferred", "uncertain", "contradicted"

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        evidence_payload = [
            {
                "evidence_type": e.evidence_type,
                "source_document_ids": e.source_document_ids,
                "related_section": e.related_section,
                "related_variable": e.related_variable,
                "observation": e.observation,
                "confidence_contribution": e.confidence_contribution,
            }
            for e in self.supporting_evidence
        ]
        return {
            "target_section": self.target_section,
            "section_name": self.target_section,
            "condition": self.condition,
            "supporting_evidence": evidence_payload,
            "evidence": evidence_payload,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class TemplateInferenceResult:
    """Result of template inference for a family."""

    family_id: str
    document_ids: list[str]
    confidence: float
    sections: list[TemplateSection] = field(default_factory=list)
    variables: list[VariableField] = field(default_factory=list)
    conditional_rules: list[ConditionalRule] = field(default_factory=list)
    evidence: list[InferenceEvidence] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "family_id": self.family_id,
            "document_ids": self.document_ids,
            "confidence": self.confidence,
            "sections": [s.to_dict() for s in self.sections],
            "variables": [v.to_dict() for v in self.variables],
            "conditional_rules": [cr.to_dict() for cr in self.conditional_rules],
            "evidence": [
                {
                    "evidence_type": e.evidence_type,
                    "source_document_ids": e.source_document_ids,
                    "related_section": e.related_section,
                    "related_variable": e.related_variable,
                    "observation": e.observation,
                    "confidence_contribution": e.confidence_contribution,
                }
                for e in self.evidence
            ],
        }
