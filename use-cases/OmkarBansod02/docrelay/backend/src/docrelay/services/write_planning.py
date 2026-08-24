import hashlib
import json
from datetime import timedelta
from enum import StrEnum
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docrelay.domain.enums import (
    ChangeDecision,
    Provider,
    ReviewRoundResolution,
    SuperDocsJobStatus,
    SyncRunState,
)
from docrelay.domain.write_plan import SealedWritePlan
from docrelay.mapping.production import (
    BaselineSnapshot,
    MappingFailure,
    MappingFailureCode,
    ProviderLocation,
    ReviewedProposal,
    SealedMappingProof,
    SemanticReplacement,
    compile_write_plan,
    map_approved_replacements,
    normalize_reviewed_change,
    write_plan_identity,
)
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    GoogleBaselineCapture,
    MappingProof,
    ProposedChange,
    ReviewDecision,
    ReviewRound,
    SourceSnapshot,
    SuperDocsDocument,
    SuperDocsExport,
    SuperDocsJob,
    SuperDocsSession,
    SyncRun,
    WritePlan,
    WritePlanLineage,
)
from docrelay.services.artifacts import ArtifactStore, ArtifactStoreError
from docrelay.services.superdocs_workflow import RunNotFound


class DryRunStatus(StrEnum):
    READY = "READY"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    STALE = "STALE"
    NOT_APPROVED = "NOT_APPROVED"


class _WritePlanningModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DryRunSource(_WritePlanningModel):
    provider: Literal[Provider.GOOGLE]
    file_id: str
    baseline_revision_id: str
    native_snapshot_sha256: str


class ContextSpan(_WritePlanningModel):
    text: str
    highlight_start: int = Field(ge=0)
    highlight_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_highlight(self) -> Self:
        if self.highlight_start >= self.highlight_end or self.highlight_end > len(self.text):
            raise ValueError("context highlight is outside the displayed text")
        return self


class ContextualReplacement(_WritePlanningModel):
    offset_unit: Literal["UNICODE_CODE_POINT"] = "UNICODE_CODE_POINT"
    before: ContextSpan
    after: ContextSpan
    source_snapshot_id: UUID
    native_snapshot_sha256: str


class DryRunMappedChange(_WritePlanningModel):
    proposal_id: UUID
    old_text: str = Field(min_length=1)
    new_text: str = Field(min_length=1)
    context: ContextualReplacement
    structural_location: dict[str, JsonValue]


class DryRunView(_WritePlanningModel):
    run_id: UUID
    proposal_id: UUID | None
    status: DryRunStatus
    source: DryRunSource | None
    old_text: str | None
    new_text: str | None
    context: ContextualReplacement | None = None
    changes: tuple[DryRunMappedChange, ...] = ()
    structural_location: dict[str, JsonValue] | None
    operation_count: int = Field(ge=0)
    operation_types: tuple[str, ...]
    provider_operation: dict[str, JsonValue] | None
    why_safe: tuple[str, ...]
    mapping_proof_id: UUID | None
    mapping_proof_sha256: str | None
    write_plan_id: UUID | None
    write_plan_sha256: str | None
    reason_code: str | None
    reason: str | None
    candidate_count: int | None
    cloud_mutation_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_context_contract(self) -> Self:
        if self.status is not DryRunStatus.READY:
            if self.context is not None or self.changes:
                raise ValueError("non-ready dry-runs cannot expose write preview context")
            return self
        if (
            self.context is None
            or self.old_text is None
            or self.new_text is None
            or not self.changes
        ):
            raise ValueError("ready dry-runs require exact contextual replacement evidence")
        first = self.changes[0]
        if (
            first.old_text != self.old_text
            or first.new_text != self.new_text
            or first.context != self.context
        ):
            raise ValueError("top-level dry-run preview must match the first mapped change")
        before = self.context.before
        after = self.context.after
        if (
            before.text[before.highlight_start : before.highlight_end] != self.old_text
            or after.text[after.highlight_start : after.highlight_end] != self.new_text
            or before.text[: before.highlight_start] != after.text[: after.highlight_start]
            or before.text[before.highlight_end :] != after.text[after.highlight_end :]
            or self.source is None
            or self.context.native_snapshot_sha256 != self.source.native_snapshot_sha256
        ):
            raise ValueError("context does not match the exact frozen replacement evidence")
        for change in self.changes:
            change_before = change.context.before
            change_after = change.context.after
            if (
                change_before.text[change_before.highlight_start : change_before.highlight_end]
                != change.old_text
                or change_after.text[change_after.highlight_start : change_after.highlight_end]
                != change.new_text
                or self.source is None
                or change.context.native_snapshot_sha256 != self.source.native_snapshot_sha256
            ):
                raise ValueError("mapped change context does not match frozen replacement evidence")
        return self


class WritePlanningService:
    """Compile persisted SuperDocs review evidence without any provider dependency."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        owner_subject: str,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self._sessions = sessions
        self._owner_subject = owner_subject
        self._artifacts = artifacts

    async def dry_run(self, run_id: UUID, *, proposal_id: UUID | None = None) -> DryRunView:
        async with self._sessions() as session:
            run, document, connection = await self._owned_run(session, run_id)
            snapshot = await session.scalar(
                select(SourceSnapshot).where(SourceSnapshot.sync_run_id == run.id)
            )
            if snapshot is None:
                return _failure_view(
                    run_id,
                    proposal_id,
                    MappingFailure(
                        MappingFailureCode.STALE_LINEAGE,
                        "run has no immutable source snapshot",
                    ),
                )
            source = DryRunSource(
                provider=Provider.GOOGLE,
                file_id=document.provider_file_id,
                baseline_revision_id=snapshot.provider_revision_id,
                native_snapshot_sha256=snapshot.native_canonical_sha256,
            )
            try:
                approved_lineage = await self._approved_review_lineage(
                    session, run, snapshot, proposal_id
                )
                export = approved_lineage[0][6]
                await self._require_export_artifact(export)
                capture = await self._baseline_capture(session, snapshot)
                baseline = BaselineSnapshot(
                    snapshot_id=snapshot.id,
                    provider=Provider.GOOGLE,
                    provider_principal_subject=connection.provider_account_subject,
                    provider_file_id=document.provider_file_id,
                    parent_ids=tuple(document.parent_ids),
                    baseline_revision_id=snapshot.provider_revision_id,
                    run_baseline_revision_id=run.baseline_revision_id or "",
                    capture_revision_id=capture.provider_revision_id,
                    native_raw_sha256=snapshot.native_raw_sha256,
                    native_canonical_sha256=snapshot.native_canonical_sha256,
                    exported_docx_sha256=snapshot.exported_artifact_sha256,
                    canonical_payload=capture.canonical_payload,
                )
                mapped_changes: list[SemanticReplacement] = []
                persisted_lineage: list[
                    tuple[ProposedChange, ReviewDecision, SemanticReplacement]
                ] = []
                for (
                    proposal,
                    decision,
                    round_row,
                    job,
                    superdocs_session,
                    superdocs_document,
                    export,
                ) in approved_lineage:
                    superseded = (
                        await session.scalar(
                            select(ProposedChange.id).where(
                                ProposedChange.replaces_proposal_id == proposal.id
                            )
                        )
                        is not None
                    )
                    lineage_current = (
                        run.state is SyncRunState.REVIEWED_EXPORT_READY
                        and run.baseline_revision_id == snapshot.provider_revision_id
                        and proposal.sync_run_id == run.id
                        and proposal.superdocs_job_id == job.id
                        and proposal.review_round_id == round_row.id
                        and proposal.target_document_id == superdocs_document.id
                        and decision.sync_run_id == run.id
                        and decision.proposed_change_id == proposal.id
                        and round_row.sync_run_id == run.id
                        and round_row.superdocs_job_id == job.id
                        and round_row.resolution is ReviewRoundResolution.SUBMIT_CHANGES
                        and job.sync_run_id == run.id
                        and job.status is SuperDocsJobStatus.COMPLETED
                        and job.superdocs_session_id == superdocs_session.id
                        and job.target_document_id == superdocs_document.id
                        and superdocs_session.sync_run_id == run.id
                        and superdocs_document.superdocs_session_id == superdocs_session.id
                        and superdocs_document.source_snapshot_id == snapshot.id
                        and export.sync_run_id == run.id
                        and export.source_snapshot_id == snapshot.id
                        and export.superdocs_session_id == superdocs_session.id
                        and export.superdocs_document_id == superdocs_document.id
                        and export.superdocs_job_id == job.id
                        and not export.warnings
                    )
                    reviewed = ReviewedProposal(
                        proposal_id=proposal.id,
                        decision_id=decision.id,
                        decision=decision.decision,
                        decision_sha256=decision.decision_sha256,
                        superseded=superseded,
                        operation=proposal.operation,
                        review_round=round_row.ordinal,
                        session_id=superdocs_session.session_id,
                        session_document_id=superdocs_document.session_document_id,
                        durable_document_id=superdocs_document.durable_document_id,
                        job_id=job.provider_job_id,
                        superdocs_export_id=export.id,
                        approved_export_sha256=export.sha256,
                        final_version_id=export.final_version_id,
                        superdocs_change_id=proposal.superdocs_change_id,
                        chunk_id=proposal.chunk_id,
                        old_html=proposal.old_html,
                        new_html=proposal.new_html,
                        lineage_current=lineage_current,
                    )
                    try:
                        change = normalize_reviewed_change(reviewed)
                    except MappingFailure as exc:
                        raise MappingFailure(
                            exc.code,
                            (
                                f"approved proposal {proposal.id} cannot be safely mapped: "
                                f"{exc.safe_message}"
                            ),
                            candidate_count=exc.candidate_count,
                            proposal_id=proposal.id,
                        ) from exc
                    mapped_changes.append(change)
                    persisted_lineage.append((proposal, decision, change))
                proof = map_approved_replacements(
                    tuple(mapped_changes), baseline, export.exported_at
                )
                changes_by_id = {item.proposal_id: item for item in mapped_changes}
                ordered_changes = tuple(
                    changes_by_id[item.lineage.proposal_id] for item in proof.payload.replacements
                )
                dry_run_changes = tuple(
                    DryRunMappedChange(
                        proposal_id=change.proposal_id,
                        old_text=change.old_text,
                        new_text=change.new_text,
                        context=_contextual_replacement(change, baseline, item.location),
                        structural_location=item.location.model_dump(mode="json"),
                    )
                    for change, item in zip(
                        ordered_changes, proof.payload.replacements, strict=True
                    )
                )
                stored_proof = await self._persist_proof(session, run, snapshot, proof)
                rule_hash = _hash_json(run.rule_snapshot)
                plan = compile_write_plan(
                    mapped=ordered_changes,
                    baseline=baseline,
                    proof=proof,
                    sync_run_id=run.id,
                    rule_identity=run.folder_rule_id
                    or uuid5(NAMESPACE_URL, f"docrelay:manual-rule:{rule_hash}"),
                    rule_version=run.folder_rule_version or 1,
                    instruction_sha256=str(
                        run.rule_snapshot.get("instruction_sha256") or rule_hash
                    ),
                    configuration_sha256=rule_hash,
                    created_at=export.exported_at,
                    expires_at=export.exported_at + timedelta(hours=24),
                )
                stored_plan = await self._persist_plan(
                    session,
                    run,
                    snapshot,
                    persisted_lineage,
                    stored_proof,
                    plan,
                )
                await session.commit()
            except MappingFailure as exc:
                await session.rollback()
                return _failure_view(
                    run_id,
                    exc.proposal_id or proposal_id,
                    exc,
                    source=source,
                )
            except ValidationError:
                await session.rollback()
                return _failure_view(
                    run_id,
                    proposal_id,
                    MappingFailure(
                        MappingFailureCode.STALE_LINEAGE,
                        "persisted planning evidence is malformed",
                    ),
                    source=source,
                )

        operation = plan.payload.provider_operations[0]
        first = dry_run_changes[0]
        why_safe: tuple[str, ...] = (
            "approved immutable review decision",
            "exact persisted baseline revision and native snapshot hash",
            "one unique ordinary body paragraph and one plain text run",
            "exact internal contiguous ASCII preimage",
            "minimum delete-and-insert range guarded by requiredRevisionId",
        )
        if len(dry_run_changes) > 1:
            why_safe = (
                *why_safe,
                "independent non-overlapping replacements on the same frozen revision",
            )
        return DryRunView(
            run_id=run_id,
            proposal_id=first.proposal_id,
            status=DryRunStatus.READY,
            source=source,
            old_text=first.old_text,
            new_text=first.new_text,
            context=first.context,
            changes=dry_run_changes,
            structural_location=first.structural_location,
            operation_count=len(operation.requests),
            operation_types=tuple(
                next(iter(request)) for request in operation.requests if isinstance(request, dict)
            ),
            provider_operation=operation.provider_payload(),
            why_safe=why_safe,
            mapping_proof_id=stored_proof.id,
            mapping_proof_sha256=proof.integrity_sha256,
            write_plan_id=stored_plan.id,
            write_plan_sha256=plan.integrity_sha256,
            reason_code=None,
            reason=None,
            candidate_count=1,
        )

    async def _require_export_artifact(self, export: SuperDocsExport) -> None:
        if self._artifacts is None:
            return
        try:
            content = await self._artifacts.read(export.artifact_reference)
        except ArtifactStoreError as exc:
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "reviewed export artifact is unavailable",
            ) from exc
        if (
            len(content) != export.size_bytes
            or hashlib.sha256(content).hexdigest() != export.sha256
        ):
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "reviewed export artifact failed immutable identity verification",
            )

    async def _owned_run(
        self, session: AsyncSession, run_id: UUID
    ) -> tuple[SyncRun, CloudDocument, CloudConnection]:
        row = (
            await session.execute(
                select(SyncRun, CloudDocument, CloudConnection)
                .join(CloudDocument, CloudDocument.id == SyncRun.cloud_document_id)
                .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
                .where(
                    SyncRun.id == run_id,
                    CloudConnection.owner_subject == self._owner_subject,
                    CloudConnection.provider == Provider.GOOGLE,
                )
            )
        ).one_or_none()
        if row is None:
            raise RunNotFound("run was not found")
        return row._tuple()

    async def _approved_review_lineage(
        self,
        session: AsyncSession,
        run: SyncRun,
        snapshot: SourceSnapshot,
        proposal_id: UUID | None,
    ) -> tuple[
        tuple[
            ProposedChange,
            ReviewDecision,
            ReviewRound,
            SuperDocsJob,
            SuperDocsSession,
            SuperDocsDocument,
            SuperDocsExport,
        ],
        ...,
    ]:
        roster = tuple(
            await session.scalars(
                select(ProposedChange)
                .where(ProposedChange.sync_run_id == run.id)
                .order_by(ProposedChange.created_at, ProposedChange.id)
            )
        )
        superseded_ids = {
            item.replaces_proposal_id for item in roster if item.replaces_proposal_id is not None
        }
        current_proposals = tuple(item for item in roster if item.id not in superseded_ids)
        current_ids = {item.id for item in current_proposals}
        decisions = tuple(
            await session.scalars(
                select(ReviewDecision).where(ReviewDecision.proposed_change_id.in_(current_ids))
            )
        )
        decisions_by_proposal = {item.proposed_change_id: item for item in decisions}
        if len(decisions_by_proposal) != len(decisions):
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "review decision lineage is ambiguous",
            )
        if proposal_id is not None:
            selected_proposal = next((item for item in roster if item.id == proposal_id), None)
            if selected_proposal is None:
                raise MappingFailure(
                    MappingFailureCode.STALE_LINEAGE,
                    "selected proposal does not belong to this review lineage",
                )
        approved = tuple(
            proposal
            for proposal in current_proposals
            if (
                (decision := decisions_by_proposal.get(proposal.id)) is not None
                and decision.decision is ChangeDecision.APPROVE
            )
        )
        if not approved:
            code = (
                MappingFailureCode.UNDECIDED
                if len(decisions_by_proposal) != len(current_proposals)
                else MappingFailureCode.NOT_APPROVED
            )
            raise MappingFailure(code, "review has no approved writable proposal")
        export = await session.scalar(
            select(SuperDocsExport).where(SuperDocsExport.sync_run_id == run.id)
        )
        if export is None:
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "review/export lineage is incomplete",
            )
        rows: list[
            tuple[
                ProposedChange,
                ReviewDecision,
                ReviewRound,
                SuperDocsJob,
                SuperDocsSession,
                SuperDocsDocument,
                SuperDocsExport,
            ]
        ] = []
        for proposal in approved:
            decision = decisions_by_proposal[proposal.id]
            round_row = await session.get(ReviewRound, proposal.review_round_id)
            job = await session.get(SuperDocsJob, proposal.superdocs_job_id)
            document = await session.get(SuperDocsDocument, proposal.target_document_id)
            if round_row is None or job is None or document is None:
                raise MappingFailure(
                    MappingFailureCode.STALE_LINEAGE,
                    "review/export lineage is incomplete",
                )
            superdocs_session = await session.get(SuperDocsSession, job.superdocs_session_id)
            if superdocs_session is None or snapshot.id != document.source_snapshot_id:
                raise MappingFailure(
                    MappingFailureCode.STALE_LINEAGE,
                    "review lineage does not bind to the source snapshot",
                )
            rows.append((proposal, decision, round_row, job, superdocs_session, document, export))
        return tuple(rows)

    async def _baseline_capture(
        self, session: AsyncSession, snapshot: SourceSnapshot
    ) -> GoogleBaselineCapture:
        raw_capture_id = snapshot.provider_evidence.get("selected_baseline_capture_id")
        try:
            capture_id = UUID(str(raw_capture_id))
        except (TypeError, ValueError) as exc:
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "source snapshot has no selected native baseline capture",
            ) from exc
        capture = await session.get(GoogleBaselineCapture, capture_id)
        if (
            capture is None
            or capture.cloud_document_id != snapshot.cloud_document_id
            or capture.provider_revision_id != snapshot.provider_revision_id
            or capture.native_raw_sha256 != snapshot.native_raw_sha256
            or capture.native_canonical_sha256 != snapshot.native_canonical_sha256
        ):
            raise MappingFailure(
                MappingFailureCode.STALE_SNAPSHOT,
                "selected native baseline capture does not match the run snapshot",
            )
        return capture

    @staticmethod
    async def _persist_proof(
        session: AsyncSession,
        run: SyncRun,
        snapshot: SourceSnapshot,
        proof: SealedMappingProof,
    ) -> MappingProof:
        existing = await session.get(MappingProof, proof.mapping_proof_id)
        payload = proof.payload.model_dump(mode="json")
        if existing is not None:
            if (
                existing.sync_run_id != run.id
                or existing.source_snapshot_id != snapshot.id
                or existing.integrity_sha256 != proof.integrity_sha256
                or existing.proof_payload != payload
            ):
                raise MappingFailure(
                    MappingFailureCode.EXISTING_PLAN_LINEAGE_MISMATCH,
                    "existing MappingProof has different immutable inputs",
                )
            return existing
        row = MappingProof(
            id=proof.mapping_proof_id,
            created_at=proof.payload.created_at,
            sync_run_id=run.id,
            source_snapshot_id=snapshot.id,
            schema_version=proof.payload.schema_version,
            mapper_version=proof.payload.mapper_version,
            integrity_sha256=proof.integrity_sha256,
            proof_payload=payload,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def _persist_plan(
        session: AsyncSession,
        run: SyncRun,
        snapshot: SourceSnapshot,
        lineage_rows: list[tuple[ProposedChange, ReviewDecision, SemanticReplacement]],
        proof: MappingProof,
        plan: SealedWritePlan,
    ) -> WritePlan:
        if not lineage_rows or any(
            decision.decision is not ChangeDecision.APPROVE
            for _proposal, decision, _change in lineage_rows
        ):
            raise MappingFailure(
                MappingFailureCode.NOT_APPROVED,
                "only approved decisions can produce a WritePlan",
            )
        expected_ids = tuple(item.proposal_id for item in plan.payload.approval_lineage)
        ordered = sorted(
            lineage_rows,
            key=lambda item: expected_ids.index(item[0].id) if item[0].id in expected_ids else -1,
        )
        if tuple(proposal.id for proposal, _decision, _change in ordered) != expected_ids:
            raise MappingFailure(
                MappingFailureCode.STALE_LINEAGE,
                "WritePlan approval lineage does not match the approved mapped set",
            )
        existing = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run.id))
        plan_id = write_plan_identity(plan)
        payload = plan.payload.model_dump(mode="json")
        if existing is not None:
            stored_lineage = tuple(
                await session.scalars(
                    select(WritePlanLineage)
                    .where(WritePlanLineage.write_plan_id == existing.id)
                    .order_by(WritePlanLineage.ordinal, WritePlanLineage.id)
                )
            )
            expected_lineage = tuple(
                (proposal.id, decision.id, ordinal)
                for ordinal, (proposal, decision, _change) in enumerate(ordered, start=1)
            )
            actual_lineage = tuple(
                (item.proposed_change_id, item.review_decision_id, item.ordinal)
                for item in stored_lineage
            )
            if (
                existing.id != plan_id
                or existing.integrity_sha256 != plan.integrity_sha256
                or existing.payload != payload
                or actual_lineage != expected_lineage
            ):
                raise MappingFailure(
                    MappingFailureCode.EXISTING_PLAN_LINEAGE_MISMATCH,
                    "an existing WritePlan has different immutable inputs",
                )
            return existing
        operation_payload = {
            "operations": [
                operation.model_dump(mode="json") for operation in plan.payload.provider_operations
            ]
        }
        row = WritePlan(
            id=plan_id,
            created_at=plan.payload.created_at,
            sync_run_id=run.id,
            source_snapshot_id=snapshot.id,
            mapping_proof_id=proof.id,
            schema_version=plan.payload.schema_version,
            provider_file_id=plan.payload.source.provider_file_id,
            baseline_revision_id=plan.payload.source.baseline_revision_id,
            mapper_version=plan.payload.mapping.mapper_version,
            verifier_version=plan.payload.expected_postimage.verifier_version,
            provider_operations=operation_payload,
            expected_postimage_sha256=plan.payload.expected_postimage.canonical_sha256,
            payload=payload,
            integrity_sha256=plan.integrity_sha256,
            sealed_at=plan.payload.created_at,
            expires_at=plan.payload.expires_at,
        )
        session.add(row)
        await session.flush()
        for ordinal, (proposal, decision, _change) in enumerate(ordered, start=1):
            session.add(
                WritePlanLineage(
                    id=uuid5(NAMESPACE_URL, f"docrelay:write-plan-lineage:{row.id}:{proposal.id}"),
                    created_at=plan.payload.created_at,
                    write_plan_id=row.id,
                    proposed_change_id=proposal.id,
                    review_decision_id=decision.id,
                    ordinal=ordinal,
                )
            )
        await session.flush()
        return row


def _failure_view(
    run_id: UUID,
    proposal_id: UUID | None,
    failure: MappingFailure,
    *,
    source: DryRunSource | None = None,
) -> DryRunView:
    if failure.code is MappingFailureCode.AMBIGUOUS_PREIMAGE:
        status = DryRunStatus.AMBIGUOUS
    elif failure.code in {
        MappingFailureCode.STALE_LINEAGE,
        MappingFailureCode.STALE_SNAPSHOT,
        MappingFailureCode.WRONG_REVISION,
        MappingFailureCode.EXISTING_PLAN_LINEAGE_MISMATCH,
    }:
        status = DryRunStatus.STALE
    elif failure.code in {MappingFailureCode.NOT_APPROVED, MappingFailureCode.UNDECIDED}:
        status = DryRunStatus.NOT_APPROVED
    else:
        status = DryRunStatus.UNSUPPORTED
    return DryRunView(
        run_id=run_id,
        proposal_id=proposal_id,
        status=status,
        source=source,
        old_text=None,
        new_text=None,
        context=None,
        structural_location=None,
        operation_count=0,
        operation_types=(),
        provider_operation=None,
        why_safe=(),
        mapping_proof_id=None,
        mapping_proof_sha256=None,
        write_plan_id=None,
        write_plan_sha256=None,
        reason_code=failure.code,
        reason=failure.safe_message,
        candidate_count=failure.candidate_count,
    )


def _hash_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _contextual_replacement(
    change: SemanticReplacement,
    baseline: BaselineSnapshot,
    location: ProviderLocation,
) -> ContextualReplacement:
    try:
        tabs = baseline.canonical_payload["tabs"]
        assert isinstance(tabs, list)
        tab = tabs[0]
        assert isinstance(tab, dict)
        body = tab["body"]
        assert isinstance(body, list)
        paragraph = body[location.structural_element_index]
        assert isinstance(paragraph, dict)
        runs = paragraph["runs"]
        assert isinstance(runs, list)
        run = runs[location.text_run_index]
        assert isinstance(run, dict)
        frozen_text = run["text"]
        assert isinstance(frozen_text, str) and frozen_text.endswith("\n")
        before = frozen_text[:-1]
    except (AssertionError, IndexError, KeyError, TypeError) as exc:
        raise MappingFailure(
            MappingFailureCode.STALE_SNAPSHOT,
            "context could not be derived from the frozen mapped source paragraph",
        ) from exc
    start = len(change.prefix)
    end = start + len(change.old_text)
    if before != change.old_paragraph or before[start:end] != change.old_text:
        raise MappingFailure(
            MappingFailureCode.STALE_LINEAGE,
            "context does not contain the exact approved source preimage",
        )
    after = f"{before[:start]}{change.new_text}{before[end:]}"
    if after != change.new_paragraph:
        raise MappingFailure(
            MappingFailureCode.STALE_LINEAGE,
            "context does not match the approved replacement paragraph",
        )
    return ContextualReplacement(
        before=ContextSpan(text=before, highlight_start=start, highlight_end=end),
        after=ContextSpan(
            text=after,
            highlight_start=start,
            highlight_end=start + len(change.new_text),
        ),
        source_snapshot_id=baseline.snapshot_id,
        native_snapshot_sha256=baseline.native_canonical_sha256,
    )
