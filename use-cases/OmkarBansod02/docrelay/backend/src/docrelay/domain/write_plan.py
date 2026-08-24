import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from docrelay.domain.enums import Provider

SHA256_PATTERN = r"^[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]


class WritePlanIntegrityError(ValueError):
    """Raised when a sealed plan no longer matches its canonical integrity hash."""


class FrozenContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSnapshotContract(FrozenContract):
    snapshot_id: UUID
    provider: Literal[Provider.GOOGLE]
    provider_principal_subject: str = Field(min_length=1)
    provider_file_id: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = Field(min_length=1)
    baseline_revision_id: str = Field(min_length=1)
    native_raw_sha256: Sha256
    native_canonical_sha256: Sha256
    exported_docx_sha256: Sha256


class RuleContract(FrozenContract):
    rule_id: UUID
    version: int = Field(ge=1)
    instruction_sha256: Sha256
    configuration_sha256: Sha256


class MappingProofContract(FrozenContract):
    mapping_proof_id: UUID
    schema_version: str = Field(min_length=1)
    mapper_version: str = Field(min_length=1)
    integrity_sha256: Sha256


class ApprovalLineageContract(FrozenContract):
    proposal_id: UUID
    decision_id: UUID
    review_round: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    session_document_id: str = Field(min_length=1)
    durable_document_id: str | None = None
    job_id: str = Field(min_length=1)
    superdocs_export_id: UUID
    approved_export_sha256: Sha256
    final_version_id: str | None = None
    superdocs_change_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    approved: Literal[True]
    old_html_sha256: Sha256
    new_html_sha256: Sha256


class GoogleDocsBatchUpdate(FrozenContract):
    operation: Literal["GOOGLE_DOCS_BATCH_UPDATE"] = "GOOGLE_DOCS_BATCH_UPDATE"
    required_revision_id: str = Field(min_length=1)
    requests: tuple[dict[str, JsonValue], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_unsafe_request_shapes(self) -> Self:
        forbidden = _find_forbidden_keys(self.requests)
        if forbidden:
            raise ValueError(f"forbidden Google write field(s): {', '.join(sorted(forbidden))}")
        return self

    def provider_payload(self) -> dict[str, JsonValue]:
        return {
            "requests": list(self.requests),
            "writeControl": {"requiredRevisionId": self.required_revision_id},
        }


class ExpectedPostimageContract(FrozenContract):
    schema_version: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    canonical_sha256: Sha256
    canonical_payload: dict[str, JsonValue]


class ExpectedReplacementContract(FrozenContract):
    old_text: str = Field(min_length=1)
    new_text: str = Field(min_length=1)
    old_paragraph_sha256: Sha256
    new_paragraph_sha256: Sha256


class PlannedReplacementContract(FrozenContract):
    proposal_id: UUID
    decision_id: UUID
    old_text: str = Field(min_length=1)
    new_text: str = Field(min_length=1)
    old_paragraph_sha256: Sha256
    new_paragraph_sha256: Sha256
    tab_id: str = Field(min_length=1)
    segment_id: Literal[""] = ""
    structural_element_index: int = Field(ge=0)
    baseline_edit_start_index: int = Field(ge=0)
    baseline_edit_end_index: int = Field(gt=0)
    google_delete_start_index: int = Field(ge=0)
    google_delete_end_index: int = Field(gt=0)
    google_insert_index: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_baseline_and_google_ranges(self) -> Self:
        if self.baseline_edit_start_index >= self.baseline_edit_end_index:
            raise ValueError("planned replacement baseline range is empty")
        if (
            self.google_delete_start_index != self.baseline_edit_start_index
            or self.google_delete_end_index != self.baseline_edit_end_index
            or self.google_insert_index != self.baseline_edit_start_index
        ):
            raise ValueError(
                "Google indexes must equal the frozen baseline range when mutations "
                "are ordered from highest baseline index to lowest"
            )
        return self


class UnsupportedChangeContract(FrozenContract):
    proposal_id: UUID | None = None
    superdocs_change_id: str | None = None
    reason_code: str = Field(min_length=1)
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class WritePlanPayload(FrozenContract):
    schema_version: Literal["docrelay.write-plan.v1"] = "docrelay.write-plan.v1"
    created_at: datetime
    expires_at: datetime
    sync_run_id: UUID
    source: SourceSnapshotContract
    rule: RuleContract
    mapping: MappingProofContract
    compiler_version: str = Field(min_length=1)
    approval_lineage: tuple[ApprovalLineageContract, ...] = Field(min_length=1)
    expected_replacement: ExpectedReplacementContract
    planned_replacements: tuple[PlannedReplacementContract, ...] = Field(min_length=1)
    provider_operations: tuple[GoogleDocsBatchUpdate, ...] = Field(min_length=1, max_length=1)
    expected_postimage: ExpectedPostimageContract
    unsupported_or_rejected_changes: tuple[UnsupportedChangeContract, ...] = ()

    @model_validator(mode="after")
    def validate_cross_contract_invariants(self) -> Self:
        if self.expires_at <= self.created_at:
            raise ValueError("WritePlan expires_at must be later than created_at")
        operation = self.provider_operations[0]
        if operation.required_revision_id != self.source.baseline_revision_id:
            raise ValueError("provider operation is not guarded by the exact baseline revision")
        if len(self.planned_replacements) != len(self.approval_lineage):
            raise ValueError("planned replacements must match the approved lineage set")
        planned_ids = tuple(item.proposal_id for item in self.planned_replacements)
        lineage_ids = tuple(item.proposal_id for item in self.approval_lineage)
        if planned_ids != lineage_ids:
            raise ValueError("planned replacement identities must match approval lineage order")
        first = self.planned_replacements[0]
        if (
            first.old_text != self.expected_replacement.old_text
            or first.new_text != self.expected_replacement.new_text
            or first.old_paragraph_sha256 != self.expected_replacement.old_paragraph_sha256
            or first.new_paragraph_sha256 != self.expected_replacement.new_paragraph_sha256
        ):
            raise ValueError("expected_replacement must mirror the first planned replacement")
        expected_requests = 2 * len(self.planned_replacements)
        if len(operation.requests) != expected_requests:
            raise ValueError(
                "provider operation count must be two requests per planned replacement"
            )
        google_order = tuple(
            sorted(
                self.planned_replacements,
                key=lambda item: (
                    -item.baseline_edit_start_index,
                    -item.baseline_edit_end_index,
                    str(item.proposal_id),
                ),
            )
        )
        for index, item in enumerate(google_order):
            delete_request = operation.requests[index * 2]
            insert_request = operation.requests[index * 2 + 1]
            if set(delete_request) != {"deleteContentRange"} or set(insert_request) != {
                "insertText"
            }:
                raise ValueError("provider operation shape is not the exact supported subset")
            range_value = delete_request["deleteContentRange"]
            if not isinstance(range_value, dict):
                raise ValueError("provider delete range is malformed")
            delete_range = range_value.get("range")
            insert_value = insert_request["insertText"]
            if not isinstance(delete_range, dict) or not isinstance(insert_value, dict):
                raise ValueError("provider mutation payload is malformed")
            location = insert_value.get("location")
            if not isinstance(location, dict):
                raise ValueError("provider insert location is malformed")
            if (
                delete_range.get("tabId") != item.tab_id
                or delete_range.get("segmentId") != item.segment_id
                or delete_range.get("startIndex") != item.google_delete_start_index
                or delete_range.get("endIndex") != item.google_delete_end_index
                or location.get("tabId") != item.tab_id
                or location.get("segmentId") != item.segment_id
                or location.get("index") != item.google_insert_index
                or insert_value.get("text") != item.new_text
            ):
                raise ValueError(
                    "provider operations are not the frozen high-to-low replacement set"
                )
        return self


class SealedWritePlan(FrozenContract):
    payload: WritePlanPayload
    integrity_sha256: Sha256

    @model_validator(mode="after")
    def verify_hash_on_load(self) -> Self:
        calculated = write_plan_sha256(self.payload)
        if calculated != self.integrity_sha256:
            raise WritePlanIntegrityError(
                f"WritePlan integrity mismatch: expected {self.integrity_sha256}, got {calculated}"
            )
        return self

    @classmethod
    def seal(cls, payload: WritePlanPayload) -> "SealedWritePlan":
        return cls(payload=payload, integrity_sha256=write_plan_sha256(payload))

    def verify_integrity(self) -> bool:
        return self.integrity_sha256 == write_plan_sha256(self.payload)


def canonical_json_bytes(value: BaseModel | dict[str, JsonValue]) -> bytes:
    serializable = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        serializable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def write_plan_sha256(payload: WritePlanPayload) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _find_forbidden_keys(value: object) -> set[str]:
    forbidden_names = {"targetRevisionId", "replaceAllText"}
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden_names:
                found.add(key)
            found.update(_find_forbidden_keys(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_find_forbidden_keys(child))
    return found
