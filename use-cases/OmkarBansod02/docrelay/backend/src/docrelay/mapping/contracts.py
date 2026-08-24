from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from docrelay.domain.write_plan import SealedWritePlan, Sha256
from docrelay.integrations.google.contracts import CanonicalReread, ConsistentBaseline
from docrelay.integrations.superdocs.contracts import PendingChange


class MappingContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MappingProofResult(MappingContract):
    mapping_proof_id: UUID
    schema_version: str = Field(min_length=1)
    mapper_version: str = Field(min_length=1)
    integrity_sha256: Sha256
    supported: bool
    proof_payload: dict[str, JsonValue]
    unsupported_reasons: tuple[str, ...] = ()


class CompileContext(MappingContract):
    sync_run_id: UUID
    rule_id: UUID
    rule_version: int = Field(ge=1)
    mapping: MappingProofResult
    proposal: PendingChange
    local_proposal_id: UUID
    local_decision_id: UUID


class PostimageVerification(MappingContract):
    verified: bool
    verifier_version: str = Field(min_length=1)
    expected_sha256: Sha256
    actual_sha256: Sha256
    report: dict[str, JsonValue]


class BaselineAlignment(Protocol):
    async def align_baseline(
        self,
        *,
        baseline: ConsistentBaseline,
        superdocs_baseline_html_reference: str,
    ) -> MappingProofResult: ...


class ApprovedChangeCompiler(Protocol):
    async def compile_approved_change(self, context: CompileContext) -> SealedWritePlan: ...


class ExpectedPostimageVerifier(Protocol):
    async def verify_expected_postimage(
        self,
        *,
        plan: SealedWritePlan,
        actual: CanonicalReread,
    ) -> PostimageVerification: ...
