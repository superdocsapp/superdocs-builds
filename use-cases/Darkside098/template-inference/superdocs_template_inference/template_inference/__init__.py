"""Template inference module for inferring document templates from clustered families."""

from superdocs_template_inference.template_inference.inferer import TemplateInferer
from superdocs_template_inference.template_inference.regeneration import (
    DocxFidelityComparator,
    DocxRegenerator,
    FidelityComparisonResult,
    RegenerationResult,
)
from superdocs_template_inference.template_inference.result import (
    ConditionalRule,
    InferenceEvidence,
    TemplateInferenceResult,
    TemplateSection,
    VariableField,
)

__all__ = [
    "TemplateInferer",
    "TemplateInferenceResult",
    "TemplateSection",
    "VariableField",
    "ConditionalRule",
    "InferenceEvidence",
    "DocxRegenerator",
    "RegenerationResult",
    "DocxFidelityComparator",
    "FidelityComparisonResult",
]
