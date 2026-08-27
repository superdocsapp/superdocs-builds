from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class InstructionType(str, Enum):
    SINGLE_SENTENCE = "single_sentence"
    ONE_SECTION = "one_section"
    TABLE_ROW = "table_row"
    GLOBAL_RENAME = "global_rename"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class LabelScope(BaseModel):
    """One acceptable interpretation of an instruction's intended scope."""

    scope_id: str
    expected_change_ids: set[str] = Field(min_length=1)
    protected_ids: set[str] = Field(default_factory=set)
    required_after_fragments: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_after_fragments: dict[str, list[str]] = Field(default_factory=dict)
    explanation: str

    @model_validator(mode="after")
    def labels_must_be_disjoint(self) -> LabelScope:
        overlap = self.expected_change_ids & self.protected_ids
        if overlap:
            raise ValueError(f"Expected and protected labels overlap: {sorted(overlap)}")
        unknown_assertions = (
            set(self.required_after_fragments) | set(self.forbidden_after_fragments)
        ) - self.expected_change_ids
        if unknown_assertions:
            raise ValueError(
                f"After-state assertions must target expected chunks: {sorted(unknown_assertions)}"
            )
        return self


class CorpusCase(BaseModel):
    case_id: str
    document: str
    instruction: str
    instruction_type: InstructionType
    label_rationale: str
    ambiguity_note: str | None = None
    labeler: str
    reviewer: str | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING
    acceptable_scopes: list[LabelScope] = Field(min_length=1)


class UnitDiff(BaseModel):
    chunk_id: str
    classification: str
    before_html: str | None
    after_html: str | None


class EvaluationScore(BaseModel):
    case_id: str
    matched_scope_id: str
    intended_change_coverage: float = Field(ge=0, le=1)
    collateral_damage_rate: float = Field(ge=0, le=1)
    precision_loss: float = Field(ge=0, le=2)
    changed_expected_ids: list[str]
    missing_expected_ids: list[str]
    incorrect_expected_ids: list[str]
    changed_protected_ids: list[str]
    unexpected_added_ids: list[str]
    unit_diffs: list[UnitDiff]


class Approach(str, Enum):
    DIRECT = "direct"
    SEARCH_SCOPED = "search_scoped"


class RunResult(BaseModel):
    run_id: str
    case_id: str
    instruction_type: InstructionType
    approach: Approach
    score: EvaluationScore
    latency_ms: int
    operations_used: int
    before_html: str
    after_html: str
    proposed_changes: list[dict] = Field(default_factory=list)
    search_chunk_ids: list[str] = Field(default_factory=list)
    chunk_id_map: dict[str, str] = Field(default_factory=dict)
    export_filename: str | None = None
    export_size_bytes: int = 0
    error: str | None = None
