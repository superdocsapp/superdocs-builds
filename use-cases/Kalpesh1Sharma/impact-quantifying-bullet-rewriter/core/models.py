from dataclasses import dataclass, field
from typing import Literal


EvidenceKind = Literal[
    "percentage",
    "currency",
    "duration",
    "volume",
    "number",
]


@dataclass(frozen=True)
class EvidenceItem:
    text: str
    kind: EvidenceKind
    start: int
    end: int


@dataclass
class BulletAnalysis:
    original_bullet: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    has_quantified_evidence: bool = False
    missing_evidence: list[str] = field(default_factory=list)


RewriteStatus = Literal[
    "ready",
    "needs_metric",
    "unsupported",
]


@dataclass
class RewriteProposal:
    original_bullet: str
    proposed_bullet: str | None
    status: RewriteStatus
    reason: str
    evidence_used: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)