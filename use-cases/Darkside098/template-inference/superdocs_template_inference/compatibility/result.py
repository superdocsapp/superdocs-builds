"""Compatibility result dataclasses."""

from dataclasses import dataclass, field


@dataclass
class CompatibilityEvidence:
    """Observable evidence for a single compatibility signal."""

    type: str
    signal_name: str
    value: float
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class CompatibilityResult:
    """Structured pairwise compatibility output between two DocumentProfile objects."""

    profile_a_id: str
    profile_b_id: str
    profile_a_filename: str
    profile_b_filename: str
    score: float
    confidence: float
    compatible: bool
    threshold: float
    evidence: list[CompatibilityEvidence]
    signal_scores: dict[str, float]
    comparison_version: str = "1.0"
