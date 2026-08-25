"""Pairwise document compatibility layer."""

from superdocs_template_inference.compatibility.config import CompatibilityConfig
from superdocs_template_inference.compatibility.result import (
    CompatibilityEvidence,
    CompatibilityResult,
)
from superdocs_template_inference.compatibility.scorer import CompatibilityScorer

__all__ = [
    "CompatibilityConfig",
    "CompatibilityEvidence",
    "CompatibilityResult",
    "CompatibilityScorer",
]
