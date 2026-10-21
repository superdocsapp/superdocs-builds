"""In-memory workspace state for the reviewer demo. Not a database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from job_architecture.architecture import ArchitectureResult
from job_architecture.framework import FrameworkDocument
from job_architecture.models import LevelDefinition, RoleEvidence
from job_architecture.propagation import ImpactAnalysis, PreservationReport, UpdatePlan


@dataclass
class ReviewSession:
    corpus_id: str
    level_id: str
    old_level: LevelDefinition
    new_level: LevelDefinition
    analysis: ImpactAnalysis
    plans: tuple[UpdatePlan, ...]
    decisions: dict[str, bool] = field(default_factory=dict)
    remote_operation: str = "local_plan"
    review_outcome: str = "pending"
    mutation_applied: bool = False
    domain_applied: bool = False
    preservation: PreservationReport | None = None
    applied_plan_ids: tuple[str, ...] = ()


@dataclass
class CorpusWorkspace:
    corpus_id: str
    analyzed: bool = False
    architecture: ArchitectureResult | None = None
    framework: FrameworkDocument | None = None
    evidences: tuple[RoleEvidence, ...] = ()
    review: ReviewSession | None = None
    last_export: dict[str, Any] | None = None


class WorkspaceStore:
    """Process-local cache. Restart clears analysis and review sessions."""

    def __init__(self) -> None:
        self._by_corpus: dict[str, CorpusWorkspace] = {}

    def workspace(self, corpus_id: str) -> CorpusWorkspace:
        existing = self._by_corpus.get(corpus_id)
        if existing is None:
            existing = CorpusWorkspace(corpus_id=corpus_id)
            self._by_corpus[corpus_id] = existing
        return existing

    def clear(self) -> None:
        self._by_corpus.clear()
