from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EvidenceFile(_Strict):
    relative_path: str
    sha256: str
    size_bytes: int
    title: str | None = None
    date: str | None = None
    owner: str | None = None
    front_matter_controls: list[str] = Field(default_factory=list)
    front_matter_has_controls_key: bool = False
    evidence_type: str | None = None
    extract_status: Literal["ok", "hash_only"] = "ok"
    injection_flags: list[str] = Field(default_factory=list)


class IndexRow(_Strict):
    row_id: str
    control_id: str
    criterion: str
    status: Literal["Present", "GAP"]
    evidence_title: str | None = None
    date: str | None = None
    owner: str | None = None
    source_path: str | None = None
    sha256: str | None = None
    gap_reason: str | None = None
    evidence_type: str | None = None

    @model_validator(mode="after")
    def _present_or_gap(self) -> "IndexRow":
        if self.status == "Present":
            if not self.source_path or not self.sha256:
                raise ValueError("Present row requires source_path and sha256")
            if self.gap_reason is not None:
                raise ValueError("Present row must not have gap_reason")
        else:
            if not self.gap_reason:
                raise ValueError("GAP row requires gap_reason")
            if self.source_path is not None or self.sha256 is not None:
                raise ValueError("GAP row must not have source_path or sha256")
        return self


class UnmappedFile(_Strict):
    relative_path: str
    sha256: str
    title: str | None = None
    reason: str


class FlaggedFile(_Strict):
    relative_path: str
    sha256: str
    injection_flags: list[str]
    reason: Literal["injection"] = "injection"


class AmbiguousItem(_Strict):
    mapping_id: str
    relative_path: str
    sha256: str
    rule_ids: list[str]
    maps_to_sets: list[list[str]]
    reason: str


class Coverage(_Strict):
    catalog_id: str
    controls_total: int
    present_rows: int
    present_controls: int
    present_control_ids: list[str]
    gap_rows: int
    unmapped_files: int
    flagged_files: int
    ambiguous_files: int


class IndexDoc(_Strict):
    schema_name: Literal["soc2_index_v1"] = "soc2_index_v1"
    catalog_id: str
    catalog_sha256: str
    org: str
    period: str
    generated_at: str
    rows: list[IndexRow]
    unmapped: list[UnmappedFile] = Field(default_factory=list)
    flagged: list[FlaggedFile] = Field(default_factory=list)
    coverage: Coverage


class FieldChange(_Strict):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    from_: Any = Field(alias="from")
    to: Any


class ChangedRow(_Strict):
    row_id: str
    fields: dict[str, FieldChange]


class Rename(_Strict):
    kind: Literal["rename"] = "rename"
    from_row_id: str
    to_row_id: str
    sha256: str


class IndexDiff(_Strict):
    schema_name: Literal["soc2_index_diff_v1"] = "soc2_index_diff_v1"
    from_run: str
    to_run: str
    from_catalog_id: str
    to_catalog_id: str
    added: list[str]
    removed: list[str]
    changed: list[ChangedRow]
    renamed: list[Rename]
    unchanged_ids: list[str]
    summary: dict[str, int]


class MappingResult(_Strict):
    rows: list[IndexRow]
    unmapped: list[UnmappedFile]
    flagged: list[FlaggedFile]
    ambiguous: list[AmbiguousItem]


class DecisionRecord(_Strict):
    schema_name: Literal["soc2_decision_v1"] = "soc2_decision_v1"
    ts: str
    actor: Literal["cli-file", "cli-all", "cli-interactive", "pipeline"] = "pipeline"
    kind: Literal["superdocs_change", "continue_prompt"]
    run_id: str
    job_id: str | None = None
    change_id: str | None = None
    document_id: str | None = None
    approved: bool
    feedback: str | None = None


class RowChunkMap(_Strict):
    index_document_id: str
    placeholder_chunk_id: str | None = None
    rows: dict[str, str] = Field(default_factory=dict)
    data_row_id_survived: bool = False


class EvidenceTab(_Strict):
    relative_path: str
    sha256: str
    document_id: str
    filename: str


class RunState(_Strict):
    schema_name: Literal["soc2_run_state_v1"] = "soc2_run_state_v1"
    stage: Literal[
        "ingest",
        "map",
        "validate",
        "render",
        "template",
        "session",
        "chat",
        "hitl",
        "ready_to_export",
        "exported",
        "done_offline",
        "failed_proof",
        "failed",
        "done",
    ]
    catalog_id: str
    catalog_sha256: str
    org: str
    period: str
    generated_at: str
    session_id: str | None = None
    job_id: str | None = None
    template_id: str | None = None
    listed_template_name: str | None = None
    index_document_id: str | None = None
    ops_charged_this_run: int = 0
    max_ops: int = 15
    evidence_root: str | None = None
    from_run: str | None = None


class Proof(_Strict):
    catalog_id: str
    present_rows: int
    present_resolved: int
    dangling: list[str] = Field(default_factory=list)
    gap_rows: int
    controls_missing_from_index: list[str] = Field(default_factory=list)
    html_row_ids: list[str] | None = None
    html_missing_gaps: list[str] | None = None
    invented: list[str] | None = None
    overreach: list[str] | None = None
    diff_summary: dict[str, int] | None = None


class CatalogControl(_Strict):
    id: str
    name: str


class Catalog(_Strict):
    id: str
    name: str = ""
    controls: list[CatalogControl]
    sha256: str = ""

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.controls]

    def name_of(self, control_id: str) -> str:
        for c in self.controls:
            if c.id == control_id:
                return c.name
        return control_id
