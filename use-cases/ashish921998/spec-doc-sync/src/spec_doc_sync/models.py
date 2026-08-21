from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


ChangeKind = Literal["added", "removed", "renamed", "changed", "deprecated"]
Decision = Literal["pending", "approved", "rejected", "escalated"]


@dataclass(frozen=True)
class SpecChange:
    id: str
    kind: ChangeKind
    location: str
    before: object | None
    after: object | None
    confidence: float
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EditProposal:
    id: str
    change_id: str
    file: str | None
    operation: Literal["replace_all", "append_section", "mark_deprecated", "escalate"]
    needle: str | None
    replacement: str | None
    occurrences: int
    confidence: float
    rationale: str
    decision: Decision = "pending"
    feedback: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    previous_spec_sha256: str
    current_spec_sha256: str
    docs_sha256: str
    preview: bool
    proposals: list[EditProposal] = field(default_factory=list)
    changes: list[SpecChange] = field(default_factory=list)
    stop_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "proposals": [item.to_dict() for item in self.proposals],
            "changes": [item.to_dict() for item in self.changes],
        }

