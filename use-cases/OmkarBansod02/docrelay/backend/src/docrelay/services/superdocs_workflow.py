import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docrelay.domain.effects import require_effect_transition
from docrelay.domain.enums import (
    BackupStatus,
    ChangeDecision,
    ConflictChoice,
    EffectOutcome,
    EffectType,
    ReviewAwaitingKind,
    ReviewRoundResolution,
    SuperDocsDocumentRole,
    SuperDocsJobStatus,
    SyncMode,
    SyncRunState,
    VerificationStatus,
    WriteAuthorizationState,
)
from docrelay.domain.state_machine import require_transition
from docrelay.integrations.superdocs.client import SuperDocsRequestError
from docrelay.integrations.superdocs.contracts import (
    ChangeReviewDecision,
    JobReference,
    JobSnapshot,
    PendingChange,
    SessionDocumentIdentity,
    SuperDocsPort,
)
from docrelay.persistence.models import (
    Backup,
    CloudConnection,
    CloudDocument,
    ExternalEffect,
    GoogleBaselineCapture,
    MappingProof,
    ProposedChange,
    ReviewDecision,
    ReviewRound,
    RunTransition,
    SourceSnapshot,
    SuperDocsDocument,
    SuperDocsExport,
    SuperDocsJob,
    SuperDocsSession,
    SyncRun,
    VerificationResult,
    WatchRunLink,
    WriteConflict,
    WritePlan,
)
from docrelay.services.artifacts import ArtifactStore, ArtifactStoreError

SUPERDOCS_EFFECT_LEASE = timedelta(minutes=15)
_TERMINAL_SUPERDOCS_JOB_STATUSES = frozenset(
    {
        SuperDocsJobStatus.COMPLETED,
        SuperDocsJobStatus.FAILED,
        SuperDocsJobStatus.CANCELLED,
    }
)


class SuperDocsWorkflowError(RuntimeError):
    code = "PHASE3_ERROR"

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class RunNotFound(SuperDocsWorkflowError):
    code = "RUN_NOT_FOUND"


class SourceNotFound(SuperDocsWorkflowError):
    code = "SOURCE_NOT_FOUND"


class SelectedBaselineChanged(SuperDocsWorkflowError):
    code = "SELECTED_BASELINE_CHANGED"


class SuperDocsNotConfigured(SuperDocsWorkflowError):
    code = "SUPERDOCS_NOT_CONFIGURED"


class ExportNotReady(SuperDocsWorkflowError):
    code = "EXPORT_NOT_READY"


class IncompleteDecisionSet(SuperDocsWorkflowError):
    code = "INCOMPLETE_DECISION_SET"


class ReviewPayloadInvalid(SuperDocsWorkflowError):
    code = "SUPERDOCS_REVIEW_PAYLOAD_INVALID"


class ReviewOperationInvalid(SuperDocsWorkflowError):
    code = "REVIEW_OPERATION_INVALID"


class RecoveryBlocked(SuperDocsWorkflowError):
    code = "SUPERDOCS_RECOVERY_BLOCKED"


class _WorkflowModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SuperDocsBaseline(_WorkflowModel):
    cloud_document_id: UUID
    provider_revision_id: str = Field(min_length=1)
    source_format: str = Field(min_length=1)
    captured_at: datetime
    native_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    native_canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exported_docx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_schema_version: str = Field(min_length=1)
    capability_evidence: dict[str, JsonValue]
    provider_evidence: dict[str, JsonValue]
    docx_bytes: bytes = Field(exclude=True, min_length=1)
    filename: str = Field(min_length=1)


class WorkflowRuleContext(_WorkflowModel):
    folder_rule_id: UUID
    folder_rule_version: int = Field(ge=1)
    intent_discriminator: str = Field(min_length=1)
    rule_snapshot: dict[str, JsonValue]


class DecisionInput(_WorkflowModel):
    proposal_id: UUID
    approve: bool
    feedback: str | None = None


class ProposalView(_WorkflowModel):
    proposal_id: UUID
    review_round: int
    change_id: str
    operation: str
    chunk_id: str | None
    document_id: str
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None
    replaces_proposal_id: UUID | None
    decision: ChangeDecision | None = None
    feedback: str | None = None


class ExportView(_WorkflowModel):
    export_id: UUID
    artifact_reference: str
    sha256: str
    size_bytes: int
    content_type: str
    content_disposition: str | None
    warnings: tuple[dict[str, JsonValue], ...]
    final_version_id: str | None
    exported_at: datetime


class ExportArtifactView(_WorkflowModel):
    metadata: ExportView
    content: bytes = Field(exclude=True, min_length=1)


class ProviderReadErrorView(_WorkflowModel):
    code: str
    operation: Literal["jobs.get"] = "jobs.get"
    retryable: Literal[True] = True
    observed_at: datetime
    occurrence_count: int = Field(ge=1)
    provider_request_id: str | None = None


class RunView(_WorkflowModel):
    run_id: UUID
    source_id: UUID
    provider_revision_id: str
    state: SyncRunState
    attention_code: str | None
    provider_read_error: ProviderReadErrorView | None = None
    session_id: str | None
    session_document_id: str | None
    durable_document_id: str | None
    upload_version_id: str | None
    final_version_id: str | None
    provider_job_id: str | None
    provider_job_status: SuperDocsJobStatus | None
    awaiting_kind: str | None
    pending_proposals: tuple[ProposalView, ...]
    export: ExportView | None
    write_back: "WriteBackRunSummary | None"
    write_authorization: WriteAuthorizationState | None


class WriteBackRunSummary(_WorkflowModel):
    status: str
    write_plan_id: UUID
    write_plan_sha256: str
    preview: "VerifiedWritePreview | None"
    backup_created: bool
    backup_verified: bool
    write_applied: bool
    structurally_verified: bool
    resulting_revision_id: str | None
    conflict_detection_stage: str | None
    conflict_decision: ConflictChoice | None


class PreviewContextSpan(_WorkflowModel):
    text: str
    highlight_start: int = Field(ge=0)
    highlight_end: int = Field(gt=0)


class PreviewContext(_WorkflowModel):
    offset_unit: Literal["UNICODE_CODE_POINT"] = "UNICODE_CODE_POINT"
    before: PreviewContextSpan
    after: PreviewContextSpan
    source_snapshot_id: UUID
    native_snapshot_sha256: str


class VerifiedWriteChange(_WorkflowModel):
    proposal_id: UUID | None = None
    old_text: str
    new_text: str
    context: PreviewContext | None


class VerifiedWritePreview(_WorkflowModel):
    old_text: str
    new_text: str
    context: PreviewContext | None
    changes: tuple[VerifiedWriteChange, ...] = ()


async def get_write_back_summary(session: AsyncSession, run: SyncRun) -> WriteBackRunSummary | None:
    plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run.id))
    if plan is None:
        return None
    backup = await session.scalar(select(Backup).where(Backup.sync_run_id == run.id))
    write_effect = await session.scalar(
        select(ExternalEffect).where(
            ExternalEffect.sync_run_id == run.id,
            ExternalEffect.effect_type == EffectType.GOOGLE_BATCH_UPDATE,
        )
    )
    verification = await session.scalar(
        select(VerificationResult)
        .where(VerificationResult.sync_run_id == run.id)
        .order_by(VerificationResult.created_at.desc())
    )
    conflict = await session.scalar(
        select(WriteConflict).where(WriteConflict.sync_run_id == run.id)
    )
    if verification is not None and verification.status is VerificationStatus.PASSED:
        status = "WRITE_VERIFIED"
    elif verification is not None:
        status = "VERIFICATION_FAILED"
    elif conflict is not None and conflict.decision is ConflictChoice.CANCEL:
        status = "CANCELLED"
    elif conflict is not None and conflict.decision is ConflictChoice.REVIEW_LATEST:
        status = "REVIEW_LATEST"
    elif conflict is not None:
        status = "CONFLICT"
    elif run.state is SyncRunState.COMMIT_OUTCOME_UNKNOWN:
        status = "ATTENTION"
    elif run.failure_code in {
        "GOOGLE_PREWRITE_CHECK_UNAVAILABLE",
        "GOOGLE_BACKUP_VERIFICATION_UNAVAILABLE",
        "GOOGLE_POSTWRITE_READ_UNAVAILABLE",
        "GOOGLE_WRITE_RECONCILIATION_UNAVAILABLE",
    }:
        status = "ATTENTION"
    elif run.state in {SyncRunState.COMMITTING, SyncRunState.VERIFYING}:
        status = "IN_PROGRESS"
    elif run.state is SyncRunState.FAILED:
        status = "FAILED"
    else:
        status = "READY"
    preview = await _verified_write_preview(session, plan) if status == "WRITE_VERIFIED" else None
    return WriteBackRunSummary(
        status=status,
        write_plan_id=plan.id,
        write_plan_sha256=plan.integrity_sha256,
        preview=preview,
        backup_created=(
            backup is not None and backup.status in {BackupStatus.CREATED, BackupStatus.VERIFIED}
        ),
        backup_verified=backup is not None and backup.status is BackupStatus.VERIFIED,
        write_applied=(
            write_effect is not None and write_effect.outcome is EffectOutcome.SUCCEEDED
        ),
        structurally_verified=(
            verification is not None and verification.status is VerificationStatus.PASSED
        ),
        resulting_revision_id=run.resulting_revision_id,
        conflict_detection_stage=conflict.detection_stage if conflict else None,
        conflict_decision=conflict.decision if conflict else None,
    )


async def _verified_write_preview(
    session: AsyncSession,
    plan: WritePlan,
) -> VerifiedWritePreview | None:
    planned = plan.payload.get("planned_replacements")
    replacement = plan.payload.get("expected_replacement")
    if not isinstance(replacement, dict):
        return None
    old_text = replacement.get("old_text")
    new_text = replacement.get("new_text")
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return None
    preview_changes: list[VerifiedWriteChange] = []
    if isinstance(planned, list):
        for item in planned:
            if not isinstance(item, dict):
                continue
            item_old = item.get("old_text")
            item_new = item.get("new_text")
            if not isinstance(item_old, str) or not isinstance(item_new, str):
                continue
            raw_proposal_id = item.get("proposal_id")
            try:
                proposal_id = UUID(str(raw_proposal_id)) if raw_proposal_id is not None else None
            except (TypeError, ValueError):
                proposal_id = None
            preview_changes.append(
                VerifiedWriteChange(
                    proposal_id=proposal_id,
                    old_text=item_old,
                    new_text=item_new,
                    context=None,
                )
            )
    if not preview_changes:
        preview_changes.append(
            VerifiedWriteChange(old_text=old_text, new_text=new_text, context=None)
        )
    preview = VerifiedWritePreview(
        old_text=old_text,
        new_text=new_text,
        context=None,
        changes=tuple(preview_changes),
    )
    snapshot = await session.get(SourceSnapshot, plan.source_snapshot_id)
    proof = await session.get(MappingProof, plan.mapping_proof_id)
    if snapshot is None or proof is None or proof.source_snapshot_id != snapshot.id:
        return preview
    try:
        capture_id = UUID(str(snapshot.provider_evidence["selected_baseline_capture_id"]))
    except (KeyError, TypeError, ValueError):
        return preview
    capture = await session.get(GoogleBaselineCapture, capture_id)
    if (
        capture is None
        or capture.native_canonical_sha256 != snapshot.native_canonical_sha256
        or capture.provider_revision_id != snapshot.provider_revision_id
    ):
        return preview
    proof_replacements = proof.proof_payload.get("replacements")
    locations_by_proposal: dict[str, dict[str, JsonValue]] = {}
    if isinstance(proof_replacements, list):
        for item in proof_replacements:
            if not isinstance(item, dict):
                continue
            lineage = item.get("lineage")
            mapped_location = item.get("location")
            if isinstance(lineage, dict) and isinstance(mapped_location, dict):
                proposal_key = lineage.get("proposal_id")
                if isinstance(proposal_key, str):
                    locations_by_proposal[proposal_key] = mapped_location
    first_location = proof.proof_payload.get("location")
    updated_changes: list[VerifiedWriteChange] = []
    for change in preview.changes:
        location: dict[str, JsonValue] | None
        if change.proposal_id is not None:
            location = locations_by_proposal.get(str(change.proposal_id))
        elif isinstance(first_location, dict):
            location = first_location
        else:
            location = None
        context = None
        if isinstance(location, dict):
            context = _preview_context_from_frozen_lineage(
                capture.canonical_payload,
                {"location": location},
                old_text=change.old_text,
                new_text=change.new_text,
                source_snapshot_id=snapshot.id,
                native_snapshot_sha256=snapshot.native_canonical_sha256,
            )
        updated_changes.append(change.model_copy(update={"context": context}))
    first_context = updated_changes[0].context if updated_changes else None
    return preview.model_copy(update={"context": first_context, "changes": tuple(updated_changes)})


def _preview_context_from_frozen_lineage(
    canonical_payload: dict[str, JsonValue],
    proof_payload: dict[str, JsonValue],
    *,
    old_text: str,
    new_text: str,
    source_snapshot_id: UUID,
    native_snapshot_sha256: str,
) -> PreviewContext | None:
    try:
        location = proof_payload["location"]
        assert isinstance(location, dict)
        tabs = canonical_payload["tabs"]
        assert isinstance(tabs, list) and len(tabs) == 1
        tab = tabs[0]
        assert isinstance(tab, dict)
        body = tab["body"]
        assert isinstance(body, list)
        structural_element_index = location["structural_element_index"]
        text_run_index = location["text_run_index"]
        run_start = location["text_run_start_index"]
        edit_start = location["edit_start_index"]
        edit_end = location["edit_end_index"]
        assert all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (
                structural_element_index,
                text_run_index,
                run_start,
                edit_start,
                edit_end,
            )
        )
        structural_element_index = cast(int, structural_element_index)
        text_run_index = cast(int, text_run_index)
        run_start = cast(int, run_start)
        edit_start = cast(int, edit_start)
        edit_end = cast(int, edit_end)
        paragraph = body[structural_element_index]
        assert isinstance(paragraph, dict)
        runs = paragraph["runs"]
        assert isinstance(runs, list)
        run = runs[text_run_index]
        assert isinstance(run, dict)
        frozen_text = run["text"]
        assert isinstance(frozen_text, str) and frozen_text.endswith("\n")
        before = frozen_text[:-1]
        start = _code_point_offset(before, edit_start - run_start)
        end = _code_point_offset(before, edit_end - run_start)
    except (AssertionError, IndexError, KeyError, TypeError, ValueError):
        return None
    if start is None or end is None or before[start:end] != old_text:
        return None
    after = f"{before[:start]}{new_text}{before[end:]}"
    return PreviewContext(
        before=PreviewContextSpan(text=before, highlight_start=start, highlight_end=end),
        after=PreviewContextSpan(
            text=after,
            highlight_start=start,
            highlight_end=start + len(new_text),
        ),
        source_snapshot_id=source_snapshot_id,
        native_snapshot_sha256=native_snapshot_sha256,
    )


def _code_point_offset(text: str, utf16_offset: int) -> int | None:
    if utf16_offset < 0:
        return None
    consumed = 0
    for index, character in enumerate(text):
        if consumed == utf16_offset:
            return index
        consumed += len(character.encode("utf-16-le")) // 2
        if consumed > utf16_offset:
            return None
    return len(text) if consumed == utf16_offset else None


class SuperDocsWorkflow:
    """Durable one-run SuperDocs state machine used by API and worker processes."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        superdocs: SuperDocsPort,
        artifacts: ArtifactStore,
        owner_subject: str,
    ) -> None:
        self._sessions = sessions
        self._superdocs = superdocs
        self._artifacts = artifacts
        self._owner_subject = owner_subject

    async def start_run(
        self,
        *,
        baseline: SuperDocsBaseline,
        instruction: str,
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        rule_context: WorkflowRuleContext | None = None,
    ) -> RunView:
        if not instruction or not instruction.strip():
            raise ValueError("instruction must not be empty")
        if hashlib.sha256(baseline.docx_bytes).hexdigest() != baseline.exported_docx_sha256:
            raise ValueError("baseline DOCX bytes do not match their immutable hash")
        instruction_hash = _sha256_text(instruction)
        if rule_context is not None and (
            rule_context.rule_snapshot.get("instruction") != instruction
            or rule_context.rule_snapshot.get("instruction_sha256") != instruction_hash
        ):
            raise ValueError("watch rule snapshot does not match the requested instruction")
        async with self._sessions() as session:
            document = await self._owned_document(session, baseline.cloud_document_id)
            intent_payload = {
                "schema": "docrelay.superdocs-edit-intent.v1",
                "connection_id": str(document.connection_id),
                "provider_file_id": document.provider_file_id,
                "provider_revision_id": baseline.provider_revision_id,
                "native_canonical_sha256": baseline.native_canonical_sha256,
                "instruction": instruction,
                "model_tier": model_tier,
                "thinking_depth": thinking_depth,
            }
            if rule_context is not None:
                intent_payload["origin_intent"] = rule_context.intent_discriminator
            intent_key = _hash_json(intent_payload)
            existing = await session.scalar(select(SyncRun).where(SyncRun.intent_key == intent_key))
            if existing is not None:
                if rule_context is not None and (
                    existing.folder_rule_id != rule_context.folder_rule_id
                    or existing.folder_rule_version != rule_context.folder_rule_version
                    or existing.rule_snapshot != rule_context.rule_snapshot
                ):
                    raise RecoveryBlocked(
                        "existing watched run does not match its frozen rule context"
                    )
                run_id = existing.id
            else:
                run_id = uuid4()
                artifact_reference = f"baselines/{run_id}.docx"
                await self._artifacts.put(
                    artifact_reference,
                    baseline.docx_bytes,
                    baseline.exported_docx_sha256,
                )
                now = datetime.now(UTC)
                run = SyncRun(
                    id=run_id,
                    cloud_document_id=document.id,
                    folder_rule_id=(
                        rule_context.folder_rule_id if rule_context is not None else None
                    ),
                    folder_rule_version=(
                        rule_context.folder_rule_version if rule_context is not None else None
                    ),
                    rule_snapshot=(
                        dict(rule_context.rule_snapshot)
                        if rule_context is not None
                        else {
                            "schema_version": "docrelay.manual-superdocs-rule.v1",
                            "instruction": instruction,
                            "instruction_sha256": instruction_hash,
                            "model_tier": model_tier,
                            "thinking_depth": thinking_depth,
                        }
                    ),
                    mode=SyncMode.PREVIEW,
                    state=SyncRunState.BASELINING,
                    state_version=2,
                    intent_key=intent_key,
                    baseline_revision_id=baseline.provider_revision_id,
                    started_at=now,
                )
                session.add(run)
                await session.flush()
                session.add_all(
                    [
                        RunTransition(
                            sync_run_id=run.id,
                            sequence=1,
                            from_state=None,
                            to_state=SyncRunState.QUEUED,
                            actor_subject=self._owner_subject,
                            reason=(
                                "watched Google document version enqueued"
                                if rule_context is not None
                                else "manual Phase 3 run created"
                            ),
                            evidence={},
                        ),
                        RunTransition(
                            sync_run_id=run.id,
                            sequence=2,
                            from_state=SyncRunState.QUEUED,
                            to_state=SyncRunState.BASELINING,
                            actor_subject=self._owner_subject,
                            reason="immutable Google baseline selected",
                            evidence={"provider_revision_id": baseline.provider_revision_id},
                        ),
                    ]
                )
                snapshot = SourceSnapshot(
                    sync_run_id=run.id,
                    cloud_document_id=document.id,
                    provider_revision_id=baseline.provider_revision_id,
                    source_format=baseline.source_format,
                    captured_at=baseline.captured_at,
                    native_raw_sha256=baseline.native_raw_sha256,
                    native_canonical_sha256=baseline.native_canonical_sha256,
                    exported_artifact_sha256=baseline.exported_docx_sha256,
                    artifact_reference=artifact_reference,
                    schema_version=baseline.canonical_schema_version,
                    capability_evidence=baseline.capability_evidence,
                    provider_evidence=baseline.provider_evidence,
                )
                session.add(snapshot)
                await session.flush()
                superdocs_session = SuperDocsSession(
                    sync_run_id=run.id,
                    session_id=f"docrelay-{run.id.hex}",
                    raw_evidence={
                        "fresh_ingestion": True,
                        "provider_revision_id": baseline.provider_revision_id,
                    },
                )
                session.add(superdocs_session)
                await session.flush()
                session.add(
                    ExternalEffect(
                        sync_run_id=run.id,
                        effect_key="superdocs-upload",
                        effect_type=EffectType.SUPERDOCS_UPLOAD,
                        outcome=EffectOutcome.NOT_STARTED,
                        request_fingerprint=_hash_json(
                            {
                                "session_id": superdocs_session.session_id,
                                "docx_sha256": baseline.exported_docx_sha256,
                                "open_mode": "replace",
                            }
                        ),
                        request_metadata={
                            "session_id": superdocs_session.session_id,
                            "docx_sha256": baseline.exported_docx_sha256,
                            "open_mode": "replace",
                        },
                        attempt_count=0,
                    )
                )
                self._transition(
                    session,
                    run,
                    SyncRunState.EDITING,
                    reason="fresh SuperDocs ingestion ready",
                    sequence=3,
                )
                await session.commit()

        if existing is not None:
            return await self.get_run(run_id)
        ingested = await self._ensure_ingested(run_id)
        if ingested is not None:
            await self._ensure_job_started(run_id)
        return await self.get_run(run_id)

    async def resume(self, run_id: UUID, *, allow_definitive_retry: bool = False) -> RunView:
        current = await self.get_run(run_id)
        if current.state is SyncRunState.REVIEWED_EXPORT_READY:
            return current
        if (
            current.attention_code in _DEFINITIVE_RETRY_ATTENTION_CODES
            and not allow_definitive_retry
        ):
            return current
        document = await self._ensure_ingested(run_id)
        if document is None:
            return await self.get_run(run_id)
        job = await self._ensure_job_started(run_id)
        if job is None:
            return await self.get_run(run_id)
        try:
            snapshot = await self._superdocs.get_job(job.provider_job_id)
        except SuperDocsRequestError as exc:
            if exc.outcome_unknown or not exc.retryable:
                raise
            await self._record_provider_read_error(run_id, exc)
            return await self.get_run(run_id)
        await self._handle_job_snapshot(run_id, snapshot)
        return await self.get_run(run_id)

    async def get_run(self, run_id: UUID) -> RunView:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            snapshot = await session.scalar(
                select(SourceSnapshot).where(SourceSnapshot.sync_run_id == run.id)
            )
            if snapshot is None:
                raise RecoveryBlocked("run has no immutable source snapshot")
            superdocs_session = await session.scalar(
                select(SuperDocsSession).where(SuperDocsSession.sync_run_id == run.id)
            )
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id
                    == (superdocs_session.id if superdocs_session else None)
                )
            )
            job = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id)
            )
            round_row = None
            proposals: tuple[ProposalView, ...] = ()
            if job is not None:
                round_row = await session.scalar(
                    select(ReviewRound)
                    .where(
                        ReviewRound.superdocs_job_id == job.id,
                        ReviewRound.resolution.is_(None),
                    )
                    .order_by(ReviewRound.ordinal.desc())
                )
                if round_row is not None:
                    proposals = await self._proposal_views(session, round_row.id)
            export = await session.scalar(
                select(SuperDocsExport).where(SuperDocsExport.sync_run_id == run.id)
            )
            write_back = await get_write_back_summary(session, run)
            watch_link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run.id)
            )
            return RunView(
                run_id=run.id,
                source_id=run.cloud_document_id,
                provider_revision_id=snapshot.provider_revision_id,
                state=run.state,
                attention_code=run.failure_code,
                provider_read_error=_provider_read_error_view(run.failure_detail),
                session_id=superdocs_session.session_id if superdocs_session else None,
                session_document_id=document.session_document_id if document else None,
                durable_document_id=document.durable_document_id if document else None,
                upload_version_id=document.upload_version_id if document else None,
                final_version_id=document.final_version_id if document else None,
                provider_job_id=job.provider_job_id if job else None,
                provider_job_status=job.status if job else None,
                awaiting_kind=round_row.awaiting_kind.value if round_row else None,
                pending_proposals=proposals,
                export=_export_view(export),
                write_back=write_back,
                write_authorization=(
                    watch_link.write_authorization_state if watch_link is not None else None
                ),
            )

    async def list_proposals(self, run_id: UUID) -> tuple[ProposalView, ...]:
        async with self._sessions() as session:
            await self._owned_run(session, run_id)
            rows = (
                await session.scalars(
                    select(ProposedChange)
                    .where(ProposedChange.sync_run_id == run_id)
                    .order_by(
                        ProposedChange.review_round_id,
                        ProposedChange.ordinal,
                        ProposedChange.created_at,
                        ProposedChange.id,
                    )
                )
            ).all()
            return tuple([await self._proposal_view(session, row) for row in rows])

    async def get_export_artifact(self, run_id: UUID) -> ExportArtifactView:
        """Return the already-reviewed artifact after rechecking its durable identity."""
        async with self._sessions() as session:
            await self._owned_run(session, run_id)
            export = await session.scalar(
                select(SuperDocsExport).where(SuperDocsExport.sync_run_id == run_id)
            )
            if export is None:
                raise ExportNotReady("reviewed SuperDocs export is not ready")
            metadata = _export_view(export)
            assert metadata is not None
        try:
            content = await self._artifacts.read(metadata.artifact_reference)
        except ArtifactStoreError as exc:
            raise RecoveryBlocked("reviewed SuperDocs export artifact is unavailable") from exc
        if (
            len(content) != metadata.size_bytes
            or hashlib.sha256(content).hexdigest() != metadata.sha256
        ):
            raise RecoveryBlocked("reviewed SuperDocs export artifact failed identity verification")
        return ExportArtifactView(metadata=metadata, content=content)

    async def list_resumable_run_ids(self, *, limit: int = 20) -> tuple[UUID, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("worker claim limit must be between 1 and 100")
        async with self._sessions() as session:
            unresolved_review_effect = (
                select(ExternalEffect.id)
                .where(
                    ExternalEffect.sync_run_id == SyncRun.id,
                    ExternalEffect.effect_type.in_(
                        (
                            EffectType.SUPERDOCS_REVIEW_SUBMISSION,
                            EffectType.SUPERDOCS_CONTINUE,
                        )
                    ),
                    ExternalEffect.outcome.in_((EffectOutcome.STARTED, EffectOutcome.UNKNOWN)),
                )
                .exists()
            )
            rows = await session.scalars(
                select(SyncRun.id)
                .join(CloudDocument, CloudDocument.id == SyncRun.cloud_document_id)
                .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
                .where(
                    CloudConnection.owner_subject == self._owner_subject,
                    (
                        (
                            (SyncRun.state == SyncRunState.EDITING)
                            & (
                                SyncRun.failure_code.is_(None)
                                | SyncRun.failure_code.in_(_AUTOMATIC_RECOVERY_ATTENTION_CODES)
                            )
                        )
                        | (
                            (SyncRun.state == SyncRunState.AWAITING_REVIEW)
                            & (
                                SyncRun.failure_code.in_(
                                    (
                                        "SUPERDOCS_REVIEW_SUBMISSION_OUTCOME_UNKNOWN",
                                        "SUPERDOCS_CONTINUE_OUTCOME_UNKNOWN",
                                    )
                                )
                                | unresolved_review_effect
                            )
                        )
                    ),
                )
                .order_by(SyncRun.updated_at, SyncRun.id)
                .limit(limit)
            )
            return tuple(rows)

    async def submit_decisions(
        self,
        run_id: UUID,
        *,
        decisions: tuple[DecisionInput, ...],
        reviewer_subject: str,
    ) -> RunView:
        if not reviewer_subject:
            raise ValueError("reviewer_subject must not be empty")
        if await self._is_immutable_decision_replay(
            run_id,
            decisions=decisions,
            reviewer_subject=reviewer_subject,
        ):
            return await self.get_run(run_id)
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            round_row, job, superdocs_session = await self._current_round_context(session, run)
            if round_row.awaiting_kind is not ReviewAwaitingKind.CHANGE_BATCH:
                raise ReviewOperationInvalid("current review gate is not a change batch")
            proposals = (
                await session.scalars(
                    select(ProposedChange)
                    .where(ProposedChange.review_round_id == round_row.id)
                    .order_by(ProposedChange.ordinal, ProposedChange.created_at, ProposedChange.id)
                )
            ).all()
            expected = {proposal.id for proposal in proposals}
            provided = [decision.proposal_id for decision in decisions]
            if len(provided) != len(set(provided)) or set(provided) != expected:
                raise IncompleteDecisionSet(
                    "every undecided proposal requires exactly one explicit decision"
                )
            by_id = {decision.proposal_id: decision for decision in decisions}
            existing_decisions = (
                await session.scalars(
                    select(ReviewDecision).where(ReviewDecision.proposed_change_id.in_(expected))
                )
            ).all()
            effect = await self._review_effect(session, run, round_row)
            return_existing = False
            if existing_decisions:
                if len(existing_decisions) != len(proposals):
                    raise RecoveryBlocked("persisted review decisions are incomplete")
                stored_by_proposal = {
                    decision.proposed_change_id: decision for decision in existing_decisions
                }
                for proposal in proposals:
                    requested = by_id[proposal.id]
                    stored = stored_by_proposal[proposal.id]
                    expected_decision = (
                        ChangeDecision.APPROVE if requested.approve else ChangeDecision.REJECT
                    )
                    if (
                        stored.decision is not expected_decision
                        or stored.feedback != requested.feedback
                    ):
                        raise ReviewOperationInvalid(
                            "submitted decisions differ from the immutable persisted set"
                        )
                if effect.outcome in {EffectOutcome.STARTED, EffectOutcome.UNKNOWN}:
                    return_existing = True
                if effect.outcome is EffectOutcome.SUCCEEDED:
                    return_existing = True
            provider_decisions: list[ChangeReviewDecision] = []
            for proposal in proposals:
                decision = by_id[proposal.id]
                decision_value = (
                    ChangeDecision.APPROVE if decision.approve else ChangeDecision.REJECT
                )
                if not existing_decisions:
                    session.add(
                        ReviewDecision(
                            sync_run_id=run.id,
                            proposed_change_id=proposal.id,
                            decision=decision_value,
                            reviewer_subject=reviewer_subject,
                            feedback=decision.feedback,
                            decision_sha256=_hash_json(
                                {
                                    "proposal_id": str(proposal.id),
                                    "decision": decision_value.value,
                                    "feedback": decision.feedback,
                                    "reviewer_subject": reviewer_subject,
                                }
                            ),
                        )
                    )
                provider_decisions.append(
                    ChangeReviewDecision(
                        change_id=proposal.superdocs_change_id,
                        approved=decision.approve,
                        feedback=decision.feedback,
                    )
                )
            if not return_existing:
                effect.request_fingerprint = _hash_json(
                    {
                        "job_id": job.provider_job_id,
                        "decisions": [item.model_dump(mode="json") for item in provider_decisions],
                    }
                )
                effect.request_metadata = {
                    "job_id": job.provider_job_id,
                    "review_round_id": str(round_row.id),
                    "change_ids": [item.change_id for item in provider_decisions],
                    "decision_count": len(provider_decisions),
                }
                self._start_effect(effect)
                await session.commit()

        if return_existing:
            return await self.get_run(run_id)

        try:
            receipt = await self._superdocs.submit_decisions(
                session_id=superdocs_session.session_id,
                job_id=job.provider_job_id,
                decisions=tuple(provider_decisions),
            )
        except SuperDocsRequestError as exc:
            await self._record_effect_error(
                run_id,
                effect_key=f"review-round:{round_row.id}",
                exc=exc,
                attention_code=(
                    "SUPERDOCS_REVIEW_SUBMISSION_OUTCOME_UNKNOWN"
                    if exc.outcome_unknown
                    else "SUPERDOCS_REVIEW_SUBMISSION_REJECTED"
                ),
            )
            return await self.get_run(run_id)

        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            stored_round = await session.get(ReviewRound, round_row.id)
            stored_effect = await self._effect_by_key(
                session, run.id, f"review-round:{round_row.id}", for_update=True
            )
            assert stored_round is not None
            if (
                stored_round.resolution is not None
                and stored_round.resolution is not ReviewRoundResolution.SUBMIT_CHANGES
            ):
                raise RecoveryBlocked("review round resolved with a contradictory decision")
            self._complete_effect_success(stored_effect)
            stored_round.resolution = ReviewRoundResolution.SUBMIT_CHANGES
            stored_round.resolved_by_subject = reviewer_subject
            stored_round.resolved_at = datetime.now(UTC)
            stored_round.receipt_evidence = receipt.safe_evidence | {
                "status": receipt.status,
                "batch_complete": receipt.batch_complete,
            }
            if run.state is SyncRunState.AWAITING_REVIEW:
                self._transition(
                    session,
                    run,
                    SyncRunState.EDITING,
                    reason="review decisions submitted",
                )
            run.failure_code = None
            run.failure_detail = None
            await session.commit()
        return await self.get_run(run_id)

    async def _is_immutable_decision_replay(
        self,
        run_id: UUID,
        *,
        decisions: tuple[DecisionInput, ...],
        reviewer_subject: str,
    ) -> bool:
        """Recognize an exact replay without resubmitting the provider mutation."""
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            if run.state is SyncRunState.AWAITING_REVIEW or not decisions:
                return False
            provided_ids = [item.proposal_id for item in decisions]
            if len(provided_ids) != len(set(provided_ids)):
                return False
            proposals = tuple(
                await session.scalars(
                    select(ProposedChange).where(
                        ProposedChange.sync_run_id == run.id,
                        ProposedChange.id.in_(provided_ids),
                    )
                )
            )
            if len(proposals) != len(provided_ids):
                return False
            round_ids = {item.review_round_id for item in proposals}
            if len(round_ids) != 1:
                return False
            round_row = await session.get(ReviewRound, next(iter(round_ids)))
            if (
                round_row is None
                or round_row.resolution is not ReviewRoundResolution.SUBMIT_CHANGES
            ):
                return False
            round_proposal_ids = set(
                await session.scalars(
                    select(ProposedChange.id).where(ProposedChange.review_round_id == round_row.id)
                )
            )
            if set(provided_ids) != round_proposal_ids:
                return False
            stored = tuple(
                await session.scalars(
                    select(ReviewDecision).where(
                        ReviewDecision.proposed_change_id.in_(round_proposal_ids)
                    )
                )
            )
            if len(stored) != len(round_proposal_ids):
                raise RecoveryBlocked("persisted review decisions are incomplete")
            requested_by_id = {item.proposal_id: item for item in decisions}
            for item in stored:
                requested = requested_by_id[item.proposed_change_id]
                expected = ChangeDecision.APPROVE if requested.approve else ChangeDecision.REJECT
                if (
                    item.decision is not expected
                    or item.feedback != requested.feedback
                    or item.reviewer_subject != reviewer_subject
                ):
                    raise ReviewOperationInvalid(
                        "submitted decisions differ from the immutable persisted set"
                    )
            return True

    async def submit_continue(
        self,
        run_id: UUID,
        *,
        should_continue: bool,
        reviewer_subject: str,
    ) -> RunView:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            round_row, job, superdocs_session = await self._current_round_context(session, run)
            if round_row.awaiting_kind is not ReviewAwaitingKind.CONTINUE_PROMPT:
                raise ReviewOperationInvalid("current review gate is not a continue prompt")
            effect = await self._review_effect(
                session,
                run,
                round_row,
                effect_type=EffectType.SUPERDOCS_CONTINUE,
            )
            return_existing = False
            if effect.outcome in {EffectOutcome.STARTED, EffectOutcome.UNKNOWN}:
                persisted_choice = effect.request_metadata.get("continue")
                if persisted_choice is not should_continue:
                    raise ReviewOperationInvalid(
                        "submitted continue decision differs from the immutable persisted choice"
                    )
                return_existing = True
            elif effect.attempt_count > 0:
                persisted_choice = effect.request_metadata.get("continue")
                if persisted_choice is not should_continue:
                    raise ReviewOperationInvalid(
                        "submitted continue decision differs from the immutable persisted choice"
                    )
            if not return_existing:
                effect.request_fingerprint = _hash_json(
                    {"job_id": job.provider_job_id, "continue": should_continue}
                )
                effect.request_metadata = {
                    "job_id": job.provider_job_id,
                    "review_round_id": str(round_row.id),
                    "continue": should_continue,
                    "reviewer_subject": reviewer_subject,
                }
                self._start_effect(effect)
                await session.commit()
        if return_existing:
            return await self.get_run(run_id)
        try:
            receipt = await self._superdocs.submit_continue(
                session_id=superdocs_session.session_id,
                job_id=job.provider_job_id,
                should_continue=should_continue,
            )
        except SuperDocsRequestError as exc:
            await self._record_effect_error(
                run_id,
                effect_key=f"review-round:{round_row.id}",
                exc=exc,
                attention_code=(
                    "SUPERDOCS_CONTINUE_OUTCOME_UNKNOWN"
                    if exc.outcome_unknown
                    else "SUPERDOCS_CONTINUE_REJECTED"
                ),
            )
            return await self.get_run(run_id)
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            stored_round = await session.get(ReviewRound, round_row.id)
            stored_effect = await self._effect_by_key(
                session, run.id, f"review-round:{round_row.id}", for_update=True
            )
            assert stored_round is not None
            resolution = (
                ReviewRoundResolution.CONTINUE if should_continue else ReviewRoundResolution.STOP
            )
            if stored_round.resolution is not None and stored_round.resolution is not resolution:
                raise RecoveryBlocked("continue round resolved with a contradictory decision")
            self._complete_effect_success(stored_effect)
            stored_round.resolution = resolution
            stored_round.resolved_by_subject = reviewer_subject
            stored_round.resolved_at = datetime.now(UTC)
            stored_round.receipt_evidence = receipt.safe_evidence | {"status": receipt.status}
            if run.state is SyncRunState.AWAITING_REVIEW:
                self._transition(
                    session,
                    run,
                    SyncRunState.EDITING,
                    reason="continue decision submitted",
                )
            run.failure_code = None
            run.failure_detail = None
            await session.commit()
        return await self.get_run(run_id)

    async def _ensure_ingested(self, run_id: UUID) -> SuperDocsDocument | None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id == superdocs_session.id
                )
            )
            if document is not None:
                document_id = document.id
                needs_resolution = document.durable_document_id is None
            else:
                document_id = None
                needs_resolution = False
            effect = await self._effect_by_key(session, run.id, "superdocs-upload")

        if document_id is not None:
            if needs_resolution:
                await self._resolve_document(run_id, document_id)
            async with self._sessions() as session:
                return await session.get(SuperDocsDocument, document_id)

        if effect.outcome in {EffectOutcome.STARTED, EffectOutcome.UNKNOWN}:
            roster = await self._superdocs.list_session_documents(
                superdocs_session.session_id, include_html=True
            )
            if len(roster) > 1:
                await self._set_attention(run_id, "SUPERDOCS_UPLOAD_RECONCILIATION_AMBIGUOUS")
                raise RecoveryBlocked("multiple documents appeared in a fresh ingestion session")
            if len(roster) == 1:
                recovered = roster[0]
                if recovered.html_sha256 is None:
                    await self._set_attention(run_id, "SUPERDOCS_UPLOAD_RECONCILIATION_INCOMPLETE")
                    raise RecoveryBlocked("uploaded document HTML could not be reconstructed")
                async with self._sessions() as session:
                    run = await self._owned_run(session, run_id, for_update=True)
                    stored_session = await self._session_for_run(session, run.id)
                    stored_snapshot = await self._snapshot_for_run(session, run.id)
                    stored_effect = await self._effect_by_key(
                        session, run.id, "superdocs-upload", for_update=True
                    )
                    existing = await session.scalar(
                        select(SuperDocsDocument).where(
                            SuperDocsDocument.superdocs_session_id == stored_session.id
                        )
                    )
                    if existing is not None:
                        if existing.session_document_id != recovered.identity.session_document_id:
                            raise RecoveryBlocked(
                                "concurrent upload recovery found a different session document"
                            )
                        self._complete_effect_success(stored_effect)
                        run.failure_code = None
                        run.failure_detail = None
                        await session.commit()
                        return existing
                    document = SuperDocsDocument(
                        superdocs_session_id=stored_session.id,
                        source_snapshot_id=stored_snapshot.id,
                        role=SuperDocsDocumentRole.TARGET,
                        session_document_id=recovered.identity.session_document_id,
                        durable_document_id=recovered.identity.durable_document_id,
                        upload_version_id=recovered.version_id,
                        baseline_html_sha256=recovered.html_sha256,
                        baseline_evidence={
                            "recovered_from_session_roster": True,
                            "chunks_count": recovered.chunks_count,
                        },
                    )
                    session.add(document)
                    self._complete_effect_success(stored_effect)
                    run.failure_code = None
                    run.failure_detail = None
                    await session.commit()
                    return document
            if effect.outcome is EffectOutcome.STARTED and not _effect_lease_expired(effect):
                return None
            await self._quarantine_unresolved_effect(
                run_id,
                effect_key="superdocs-upload",
                attention_code="SUPERDOCS_UPLOAD_OUTCOME_UNKNOWN",
            )
            return None

        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            stored_session = await self._session_for_run(session, run.id)
            stored_snapshot = await self._snapshot_for_run(session, run.id)
            artifact_reference = stored_snapshot.artifact_reference
            if artifact_reference is None:
                raise RecoveryBlocked("baseline artifact identity is missing")
            filename = f"docrelay-{run.id}.docx"
            artifact_sha256 = stored_snapshot.exported_artifact_sha256
            stored_session_id = stored_session.id
            provider_session_id = stored_session.session_id
            stored_snapshot_id = stored_snapshot.id
        try:
            docx_bytes = await self._artifacts.read(artifact_reference)
        except ArtifactStoreError as exc:
            await self._set_attention(run_id, "SUPERDOCS_BASELINE_ARTIFACT_UNAVAILABLE")
            raise RecoveryBlocked("baseline artifact is unavailable") from exc
        if hashlib.sha256(docx_bytes).hexdigest() != artifact_sha256:
            await self._set_attention(run_id, "SUPERDOCS_BASELINE_ARTIFACT_INTEGRITY_FAILED")
            raise RecoveryBlocked("baseline artifact failed immutable identity verification")
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            stored_effect = await self._effect_by_key(
                session, run.id, "superdocs-upload", for_update=True
            )
            if stored_effect.outcome is not EffectOutcome.NOT_STARTED:
                return None
            current_session = await self._session_for_run(session, run.id)
            current_snapshot = await self._snapshot_for_run(session, run.id)
            if (
                current_session.id != stored_session_id
                or current_snapshot.artifact_reference != artifact_reference
                or current_snapshot.exported_artifact_sha256 != artifact_sha256
            ):
                raise RecoveryBlocked("baseline upload identity changed before effect claim")
            self._start_effect(stored_effect)
            await session.commit()
        try:
            uploaded = await self._superdocs.upload_docx(
                docx_bytes=docx_bytes,
                filename=filename,
                session_id=provider_session_id,
                open_mode="replace",
            )
        except SuperDocsRequestError as exc:
            await self._record_effect_error(
                run_id,
                effect_key="superdocs-upload",
                exc=exc,
                attention_code=(
                    "SUPERDOCS_UPLOAD_OUTCOME_UNKNOWN"
                    if exc.outcome_unknown
                    else "SUPERDOCS_UPLOAD_REJECTED"
                ),
            )
            return None
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            stored_session = await self._session_for_run(session, run.id)
            stored_snapshot = await self._snapshot_for_run(session, run.id)
            stored_effect = await self._effect_by_key(
                session, run.id, "superdocs-upload", for_update=True
            )
            if uploaded.identity.session_id != provider_session_id:
                raise RecoveryBlocked("upload returned an unexpected session identity")
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id == stored_session_id
                )
            )
            if document is not None:
                if document.session_document_id != uploaded.identity.session_document_id:
                    raise RecoveryBlocked(
                        "concurrent upload completion found a different session document"
                    )
            else:
                document = SuperDocsDocument(
                    superdocs_session_id=stored_session_id,
                    source_snapshot_id=stored_snapshot_id,
                    role=SuperDocsDocumentRole.TARGET,
                    session_document_id=uploaded.identity.session_document_id,
                    durable_document_id=uploaded.identity.durable_document_id,
                    upload_version_id=uploaded.upload_version_id,
                    baseline_html_sha256=uploaded.baseline_html_sha256,
                    baseline_evidence=uploaded.safe_evidence
                    | {"chunks_count": uploaded.chunks_count, "target_resolved": False},
                )
                session.add(document)
            self._complete_effect_success(stored_effect)
            run.failure_code = None
            run.failure_detail = None
            await session.commit()
            document_id = document.id
        await self._resolve_document(run_id, document_id)
        async with self._sessions() as session:
            return await session.get(SuperDocsDocument, document_id)

    async def _resolve_document(self, run_id: UUID, document_id: UUID) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.get(SuperDocsDocument, document_id)
            if document is None:
                raise RecoveryBlocked("uploaded document record is missing")
            expected_id = document.session_document_id
        roster = await self._superdocs.list_session_documents(superdocs_session.session_id)
        matches = [item for item in roster if item.identity.session_document_id == expected_id]
        if len(matches) != 1 or matches[0].identity.durable_document_id is None:
            await self._set_attention(run_id, "SUPERDOCS_TARGET_RESOLUTION_FAILED")
            raise RecoveryBlocked("exact uploaded target could not be resolved from the roster")
        resolved = matches[0]
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            document = await session.get(SuperDocsDocument, document_id)
            assert document is not None
            document.durable_document_id = resolved.identity.durable_document_id
            evidence = dict(document.baseline_evidence)
            evidence.update(
                {
                    "target_resolved": True,
                    "roster_focused_at_resolution": resolved.focused,
                    "roster_chunks_count": resolved.chunks_count,
                }
            )
            document.baseline_evidence = evidence
            run.failure_code = None
            run.failure_detail = None
            await session.commit()

    async def _ensure_job_started(self, run_id: UUID) -> SuperDocsJob | None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            existing = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id)
            )
            if existing is not None:
                return existing
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id == superdocs_session.id
                )
            )
            if document is None or document.durable_document_id is None:
                raise RecoveryBlocked("exact SuperDocs target is not resolved")
            effect = await session.scalar(
                select(ExternalEffect).where(
                    ExternalEffect.sync_run_id == run.id,
                    ExternalEffect.effect_type == EffectType.SUPERDOCS_JOB_START,
                )
            )
            if effect is None:
                effect = ExternalEffect(
                    sync_run_id=run.id,
                    effect_key="superdocs-job-start",
                    effect_type=EffectType.SUPERDOCS_JOB_START,
                    outcome=EffectOutcome.NOT_STARTED,
                    request_fingerprint=_job_start_fingerprint(run, superdocs_session, document),
                    request_metadata={
                        "session_id": superdocs_session.session_id,
                        "session_document_id": document.session_document_id,
                        "approval_mode": "ask_every_time",
                    },
                    attempt_count=0,
                )
                session.add(effect)
                await session.commit()

        if effect.outcome in {EffectOutcome.STARTED, EffectOutcome.UNKNOWN}:
            jobs = await self._superdocs.recover_session_jobs(superdocs_session.session_id)
            if len(jobs) > 1:
                await self._set_attention(run_id, "SUPERDOCS_JOB_RECONCILIATION_AMBIGUOUS")
                raise RecoveryBlocked("multiple jobs exist in a single-run SuperDocs session")
            if len(jobs) == 1:
                return await self._persist_recovered_job(run_id, jobs[0])
            if effect.outcome is EffectOutcome.STARTED and not _effect_lease_expired(effect):
                return None
            await self._quarantine_unresolved_effect(
                run_id,
                effect_key="superdocs-job-start",
                attention_code="SUPERDOCS_JOB_START_OUTCOME_UNKNOWN",
            )
            return None

        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id == superdocs_session.id
                )
            )
            assert document is not None
            effect = await self._effect_by_key(
                session, run.id, "superdocs-job-start", for_update=True
            )
            if effect.outcome is not EffectOutcome.NOT_STARTED:
                return None
            instruction = run.rule_snapshot.get("instruction")
            if not isinstance(instruction, str) or not instruction:
                raise RecoveryBlocked("persisted edit instruction is missing")
            model_tier = _json_optional_string(run.rule_snapshot.get("model_tier"))
            thinking_depth = _json_optional_string(run.rule_snapshot.get("thinking_depth"))
            target = _target_identity(superdocs_session, document)
            self._start_effect(effect)
            await session.commit()
        try:
            reference = await self._superdocs.start_edit(
                target=target,
                instruction=instruction,
                approval_mode="ask_every_time",
                model_tier=model_tier,
                thinking_depth=thinking_depth,
            )
        except SuperDocsRequestError as exc:
            await self._record_effect_error(
                run_id,
                effect_key="superdocs-job-start",
                exc=exc,
                attention_code=(
                    "SUPERDOCS_JOB_START_OUTCOME_UNKNOWN"
                    if exc.outcome_unknown
                    else "SUPERDOCS_JOB_START_REJECTED"
                ),
            )
            return None
        return await self._persist_started_job(run_id, reference)

    async def _persist_started_job(self, run_id: UUID, reference: JobReference) -> SuperDocsJob:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.scalar(
                select(SuperDocsDocument).where(
                    SuperDocsDocument.superdocs_session_id == superdocs_session.id
                )
            )
            assert document is not None
            if reference.session_id != superdocs_session.session_id:
                raise RecoveryBlocked("started job belongs to an unexpected session")
            effect = await self._effect_by_key(
                session, run.id, "superdocs-job-start", for_update=True
            )
            existing = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id)
            )
            if existing is not None:
                if existing.provider_job_id != reference.job_id:
                    run.failure_code = "SUPERDOCS_JOB_RECONCILIATION_AMBIGUOUS"
                    run.failure_detail = {
                        "persisted_job_id": existing.provider_job_id,
                        "observed_job_id": reference.job_id,
                    }
                    await session.commit()
                    raise RecoveryBlocked(
                        "concurrent job completion found a different provider job"
                    )
                self._complete_effect_success(effect)
                run.failure_code = None
                run.failure_detail = None
                await session.commit()
                return existing
            job = SuperDocsJob(
                sync_run_id=run.id,
                superdocs_session_id=superdocs_session.id,
                target_document_id=document.id,
                provider_job_id=reference.job_id,
                status=reference.status,
                start_request_sha256=effect.request_fingerprint,
                raw_state={"status": reference.status.value},
                usage_evidence={},
                started_at=datetime.now(UTC),
            )
            session.add(job)
            self._complete_effect_success(effect)
            run.failure_code = None
            run.failure_detail = None
            await session.commit()
            return job

    async def _persist_recovered_job(self, run_id: UUID, snapshot: JobSnapshot) -> SuperDocsJob:
        job = await self._persist_started_job(run_id, snapshot.reference)
        await self._update_job(run_id, snapshot)
        async with self._sessions() as session:
            stored = await session.get(SuperDocsJob, job.id)
            assert stored is not None
            return stored

    async def _handle_job_snapshot(self, run_id: UUID, snapshot: JobSnapshot) -> None:
        job = await self._update_job(run_id, snapshot)
        status = job.status
        if status in {SuperDocsJobStatus.PENDING, SuperDocsJobStatus.IN_PROGRESS}:
            await self._reconcile_resolved_review(run_id, snapshot)
            return
        if status is SuperDocsJobStatus.AWAITING_APPROVAL:
            await self._persist_review_gate(run_id, job, snapshot)
            return
        if status in {SuperDocsJobStatus.FAILED, SuperDocsJobStatus.CANCELLED}:
            async with self._sessions() as session:
                run = await self._owned_run(session, run_id, for_update=True)
                target = (
                    SyncRunState.CANCELLED
                    if status is SuperDocsJobStatus.CANCELLED
                    else SyncRunState.FAILED
                )
                self._transition(session, run, target, reason=f"SuperDocs job {status.value}")
                run.failure_code = f"SUPERDOCS_JOB_{status.value.upper()}"
                run.failure_detail = {"provider_error_code": snapshot.error_code}
                run.finished_at = datetime.now(UTC)
                await session.commit()
            return
        if status is SuperDocsJobStatus.COMPLETED:
            await self._reconcile_resolved_review(run_id, snapshot)
            await self._require_resolved_review_ledger(run_id)
            await self._export_completed_job(run_id, job.id)

    async def _require_resolved_review_ledger(self, run_id: UUID) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            unresolved_rounds = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ReviewRound)
                    .where(
                        ReviewRound.sync_run_id == run.id,
                        ReviewRound.resolution.is_(None),
                    )
                )
                or 0
            )
            undecided_proposals = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ProposedChange)
                    .outerjoin(
                        ReviewDecision,
                        ReviewDecision.proposed_change_id == ProposedChange.id,
                    )
                    .where(
                        ProposedChange.sync_run_id == run.id,
                        ReviewDecision.id.is_(None),
                    )
                )
                or 0
            )
            if unresolved_rounds or undecided_proposals:
                run.failure_code = "SUPERDOCS_COMPLETED_WITH_UNRESOLVED_REVIEW"
                run.failure_detail = {
                    "unresolved_round_count": unresolved_rounds,
                    "undecided_proposal_count": undecided_proposals,
                }
                await session.commit()
                raise RecoveryBlocked(
                    "completed SuperDocs job still has unresolved explicit review lineage"
                )

    async def _update_job(self, run_id: UUID, snapshot: JobSnapshot) -> SuperDocsJob:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            job = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id).with_for_update()
            )
            if job is None:
                raise RecoveryBlocked("persisted SuperDocs job is missing")
            superdocs_session = await self._session_for_run(session, run.id)
            if (
                snapshot.reference.job_id != job.provider_job_id
                or snapshot.reference.session_id != superdocs_session.session_id
            ):
                raise RecoveryBlocked("job observation did not match persisted identity")
            if (
                job.status in _TERMINAL_SUPERDOCS_JOB_STATUSES
                and snapshot.reference.status is not job.status
            ):
                if snapshot.reference.status in _TERMINAL_SUPERDOCS_JOB_STATUSES:
                    raise RecoveryBlocked("SuperDocs returned contradictory terminal job states")
                return job
            job.status = snapshot.reference.status
            job.raw_state = {
                "status": snapshot.reference.status.value,
                "progress": snapshot.progress,
                "awaiting_kind": snapshot.awaiting_kind,
                "pending_change_ids": [item.change_id for item in snapshot.pending_changes],
                "final_version_id": snapshot.final_version_id,
                "updated_html_sha256": snapshot.updated_html_sha256,
                "final_change_statuses": snapshot.final_change_statuses,
                "safe_metadata": snapshot.safe_metadata,
                "error_code": snapshot.error_code,
            }
            job.usage_evidence = snapshot.usage
            detail = dict(run.failure_detail or {})
            detail.pop("provider_read_error", None)
            if run.failure_code in _PROVIDER_READ_ATTENTION_CODES:
                run.failure_code = None
            run.failure_detail = detail or None
            if snapshot.reference.status is SuperDocsJobStatus.COMPLETED:
                job.completed_at = datetime.now(UTC)
                document = await session.get(SuperDocsDocument, job.target_document_id)
                assert document is not None
                if snapshot.final_version_id is not None:
                    document.final_version_id = snapshot.final_version_id
            await session.commit()
            return job

    async def _persist_review_gate(
        self, run_id: UUID, job: SuperDocsJob, snapshot: JobSnapshot
    ) -> None:
        if snapshot.awaiting_kind == "continue_prompt":
            if snapshot.pending_changes:
                await self._invalid_review(run_id, "continue prompt also contained pending changes")
            awaiting_kind = ReviewAwaitingKind.CONTINUE_PROMPT
        else:
            if not snapshot.pending_changes:
                await self._invalid_review(run_id, "change review did not contain pending changes")
            awaiting_kind = ReviewAwaitingKind.CHANGE_BATCH
        change_ids = [item.change_id for item in snapshot.pending_changes]
        if len(change_ids) != len(set(change_ids)):
            await self._invalid_review(run_id, "change review contained duplicate change IDs")

        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            stored_job = await session.get(SuperDocsJob, job.id)
            assert stored_job is not None
            target = await session.get(SuperDocsDocument, stored_job.target_document_id)
            assert target is not None
            if any(
                change.document_id != target.session_document_id
                for change in snapshot.pending_changes
            ):
                await session.rollback()
                await self._invalid_review(run_id, "proposal targeted a different document")
            unresolved = await session.scalar(
                select(ReviewRound)
                .where(
                    ReviewRound.superdocs_job_id == stored_job.id,
                    ReviewRound.resolution.is_(None),
                )
                .order_by(ReviewRound.ordinal.desc())
            )
            if unresolved is not None:
                existing_ids = set(
                    await session.scalars(
                        select(ProposedChange.superdocs_change_id).where(
                            ProposedChange.review_round_id == unresolved.id
                        )
                    )
                )
                if unresolved.awaiting_kind is awaiting_kind and existing_ids == set(change_ids):
                    effect = await session.scalar(
                        select(ExternalEffect).where(
                            ExternalEffect.sync_run_id == run.id,
                            ExternalEffect.effect_key == f"review-round:{unresolved.id}",
                        )
                    )
                    decisions = (
                        await session.scalars(
                            select(ReviewDecision)
                            .join(
                                ProposedChange,
                                ProposedChange.id == ReviewDecision.proposed_change_id,
                            )
                            .where(ProposedChange.review_round_id == unresolved.id)
                        )
                    ).all()
                    proposals = (
                        await session.scalars(
                            select(ProposedChange).where(
                                ProposedChange.review_round_id == unresolved.id
                            )
                        )
                    ).all()
                    if (
                        effect is not None
                        and effect.outcome in {EffectOutcome.STARTED, EffectOutcome.UNKNOWN}
                        and decisions
                        and _pending_batch_decisions_match(
                            snapshot.pending_batch_decisions,
                            proposals,
                            decisions,
                        )
                    ):
                        self._reconcile_effect_success(effect)
                        unresolved.resolution = ReviewRoundResolution.SUBMIT_CHANGES
                        unresolved.resolved_by_subject = decisions[0].reviewer_subject
                        unresolved.resolved_at = datetime.now(UTC)
                        unresolved.receipt_evidence = {
                            "reconciled_from_pending_batch_decisions": True
                        }
                        if run.state is SyncRunState.AWAITING_REVIEW:
                            self._transition(
                                session,
                                run,
                                SyncRunState.EDITING,
                                reason="review decisions reconciled from provider metadata",
                            )
                        run.failure_code = None
                        run.failure_detail = None
                        await session.commit()
                        return
                    if run.state is SyncRunState.EDITING:
                        self._transition(
                            session,
                            run,
                            SyncRunState.AWAITING_REVIEW,
                            reason="SuperDocs review remains pending",
                        )
                        await session.commit()
                    return
                await session.rollback()
                await self._invalid_review(
                    run_id, "a second review gate replaced an unresolved gate"
                )
            ordinal = await session.scalar(
                select(func.coalesce(func.max(ReviewRound.ordinal), 0)).where(
                    ReviewRound.superdocs_job_id == stored_job.id
                )
            )
            round_row = ReviewRound(
                sync_run_id=run.id,
                superdocs_job_id=stored_job.id,
                ordinal=int(ordinal or 0) + 1,
                awaiting_kind=awaiting_kind,
                raw_pending_evidence={
                    "provider_awaiting_kind": snapshot.awaiting_kind,
                    "change_ids": change_ids,
                    "pending_batch_decision_ids": list(snapshot.pending_batch_decisions),
                },
            )
            session.add(round_row)
            await session.flush()
            for proposal_ordinal, change in enumerate(snapshot.pending_changes, start=1):
                replacement = await self._replacement_candidate(session, run.id, change)
                raw_payload = _proposal_payload(change)
                session.add(
                    ProposedChange(
                        sync_run_id=run.id,
                        superdocs_job_id=stored_job.id,
                        review_round_id=round_row.id,
                        target_document_id=target.id,
                        replaces_proposal_id=replacement.id if replacement else None,
                        superdocs_change_id=change.change_id,
                        ordinal=proposal_ordinal,
                        operation=change.operation,
                        chunk_id=change.chunk_id,
                        old_html=change.old_html,
                        new_html=change.new_html,
                        ai_explanation=change.ai_explanation,
                        payload_sha256=_hash_json(raw_payload),
                        raw_payload=raw_payload,
                    )
                )
            if run.state is SyncRunState.EDITING:
                self._transition(
                    session,
                    run,
                    SyncRunState.AWAITING_REVIEW,
                    reason="SuperDocs requires explicit human review",
                )
            run.failure_code = None
            run.failure_detail = None
            await session.commit()

    async def _invalid_review(self, run_id: UUID, detail: str) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            if run.state is SyncRunState.EDITING:
                self._transition(
                    session,
                    run,
                    SyncRunState.AWAITING_REVIEW,
                    reason="invalid SuperDocs review payload requires attention",
                )
            run.failure_code = ReviewPayloadInvalid.code
            run.failure_detail = {"reason": detail}
            await session.commit()
        raise ReviewPayloadInvalid("SuperDocs review payload was missing or contradictory")

    async def _reconcile_resolved_review(self, run_id: UUID, snapshot: JobSnapshot) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            job = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id)
            )
            if job is None:
                return
            round_row = await session.scalar(
                select(ReviewRound)
                .where(
                    ReviewRound.superdocs_job_id == job.id,
                    ReviewRound.resolution.is_(None),
                )
                .order_by(ReviewRound.ordinal.desc())
            )
            if round_row is None:
                if run.state is SyncRunState.AWAITING_REVIEW:
                    self._transition(
                        session,
                        run,
                        SyncRunState.EDITING,
                        reason="provider moved beyond review gate",
                    )
                    await session.commit()
                return
            effect = await session.scalar(
                select(ExternalEffect).where(
                    ExternalEffect.sync_run_id == run.id,
                    ExternalEffect.effect_key == f"review-round:{round_row.id}",
                )
            )
            if effect is None or effect.outcome not in {
                EffectOutcome.STARTED,
                EffectOutcome.UNKNOWN,
            }:
                return
            self._reconcile_effect_success(effect)
            if round_row.awaiting_kind is ReviewAwaitingKind.CHANGE_BATCH:
                round_row.resolution = ReviewRoundResolution.SUBMIT_CHANGES
                decision = await session.scalar(
                    select(ReviewDecision)
                    .join(
                        ProposedChange,
                        ProposedChange.id == ReviewDecision.proposed_change_id,
                    )
                    .where(ProposedChange.review_round_id == round_row.id)
                    .limit(1)
                )
                round_row.resolved_by_subject = (
                    decision.reviewer_subject if decision is not None else None
                )
            else:
                should_continue = effect.request_metadata.get("continue")
                if not isinstance(should_continue, bool):
                    raise RecoveryBlocked(
                        "persisted continue decision is missing during reconciliation"
                    )
                round_row.resolution = (
                    ReviewRoundResolution.CONTINUE
                    if should_continue
                    else ReviewRoundResolution.STOP
                )
                round_row.resolved_by_subject = _json_optional_string(
                    effect.request_metadata.get("reviewer_subject")
                )
            round_row.resolved_at = datetime.now(UTC)
            round_row.receipt_evidence = {
                "reconciled_from_job_status": snapshot.reference.status.value
            }
            if run.state is SyncRunState.AWAITING_REVIEW:
                self._transition(
                    session,
                    run,
                    SyncRunState.EDITING,
                    reason="review submission reconciled from same job",
                )
            run.failure_code = None
            run.failure_detail = None
            await session.commit()

    async def _export_completed_job(self, run_id: UUID, job_id: UUID) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            existing = await session.scalar(
                select(SuperDocsExport).where(SuperDocsExport.sync_run_id == run.id)
            )
            if existing is not None:
                if run.state is SyncRunState.EDITING:
                    self._transition(
                        session,
                        run,
                        SyncRunState.REVIEWED_EXPORT_READY,
                        reason="reviewed SuperDocs export already persisted",
                    )
                    await session.commit()
                return
            job = await session.get(SuperDocsJob, job_id)
            if job is None or job.status is not SuperDocsJobStatus.COMPLETED:
                raise RecoveryBlocked("export was attempted before actual job completion")
            superdocs_session = await self._session_for_run(session, run.id)
            document = await session.get(SuperDocsDocument, job.target_document_id)
            snapshot = await self._snapshot_for_run(session, run.id)
            assert document is not None
            target = _target_identity(superdocs_session, document)
            focus_ordinal = (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(ExternalEffect)
                        .where(
                            ExternalEffect.sync_run_id == run.id,
                            ExternalEffect.effect_type == EffectType.SUPERDOCS_FOCUS,
                        )
                    )
                    or 0
                )
                + 1
            )
            focus_effect = ExternalEffect(
                sync_run_id=run.id,
                effect_key=f"superdocs-focus:{focus_ordinal}",
                effect_type=EffectType.SUPERDOCS_FOCUS,
                outcome=EffectOutcome.STARTED,
                request_fingerprint=_hash_json(
                    {
                        "session_id": target.session_id,
                        "document_id": target.session_document_id,
                        "attempt": focus_ordinal,
                    }
                ),
                request_metadata={
                    "session_id": target.session_id,
                    "session_document_id": target.session_document_id,
                    "attempt": focus_ordinal,
                },
                attempt_count=1,
                started_at=datetime.now(UTC),
            )
            session.add(focus_effect)
            await session.commit()
            source_snapshot_id = snapshot.id
            superdocs_session_id = superdocs_session.id
            document_id = document.id
            local_job_id = job.id

        try:
            focused = await self._superdocs.focus_document(target)
        except SuperDocsRequestError as exc:
            await self._record_effect_error(
                run_id,
                effect_key=f"superdocs-focus:{focus_ordinal}",
                exc=exc,
                attention_code="SUPERDOCS_FOCUS_OUTCOME_UNKNOWN",
            )
            raise
        if (
            not focused.focused
            or focused.identity.session_document_id != target.session_document_id
        ):
            await self._set_attention(run_id, "SUPERDOCS_FOCUS_MISMATCH")
            raise RecoveryBlocked("SuperDocs did not confirm the exact export target focus")
        async with self._sessions() as session:
            effect = await self._effect_by_key(
                session, run_id, f"superdocs-focus:{focus_ordinal}", for_update=True
            )
            self._succeed_effect(effect)
            await session.commit()

        exported = await self._superdocs.export_docx(
            target=target,
            filename=f"docrelay-reviewed-{run_id}.docx",
        )
        artifact_reference = f"exports/{run_id}/{local_job_id}.docx"
        await self._artifacts.put(artifact_reference, exported.docx_bytes, exported.sha256)
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            job = await session.get(SuperDocsJob, local_job_id)
            document = await session.get(SuperDocsDocument, document_id)
            assert job is not None and document is not None
            if job.status is not SuperDocsJobStatus.COMPLETED:
                raise RecoveryBlocked("job completion changed before export persistence")
            existing = await session.scalar(
                select(SuperDocsExport).where(SuperDocsExport.superdocs_job_id == job.id)
            )
            if existing is None:
                session.add(
                    SuperDocsExport(
                        sync_run_id=run.id,
                        source_snapshot_id=source_snapshot_id,
                        superdocs_session_id=superdocs_session_id,
                        superdocs_document_id=document.id,
                        superdocs_job_id=job.id,
                        artifact_reference=artifact_reference,
                        sha256=exported.sha256,
                        size_bytes=exported.size_bytes,
                        content_type=exported.content_type,
                        content_disposition=exported.content_disposition,
                        warnings_raw=exported.warnings_raw,
                        warnings=[cast(dict[str, Any], item) for item in exported.warnings],
                        final_version_id=document.final_version_id,
                        exported_at=datetime.now(UTC),
                    )
                )
            if run.state is SyncRunState.EDITING:
                self._transition(
                    session,
                    run,
                    SyncRunState.REVIEWED_EXPORT_READY,
                    reason="completed job explicitly focused and exported",
                )
            run.failure_code = None
            run.failure_detail = None
            await session.commit()

    async def _replacement_candidate(
        self, session: AsyncSession, run_id: UUID, change: PendingChange
    ) -> ProposedChange | None:
        if change.chunk_id is None:
            return None
        candidates = (
            await session.scalars(
                select(ProposedChange)
                .join(ReviewDecision, ReviewDecision.proposed_change_id == ProposedChange.id)
                .where(
                    ProposedChange.sync_run_id == run_id,
                    ProposedChange.chunk_id == change.chunk_id,
                    ReviewDecision.decision == ChangeDecision.REJECT,
                    ReviewDecision.feedback.is_not(None),
                )
                .order_by(ProposedChange.created_at.desc())
            )
        ).all()
        return candidates[0] if len(candidates) == 1 else None

    async def _proposal_views(
        self, session: AsyncSession, review_round_id: UUID
    ) -> tuple[ProposalView, ...]:
        rows = (
            await session.scalars(
                select(ProposedChange)
                .where(ProposedChange.review_round_id == review_round_id)
                .order_by(ProposedChange.ordinal, ProposedChange.created_at, ProposedChange.id)
            )
        ).all()
        return tuple([await self._proposal_view(session, row) for row in rows])

    async def _proposal_view(self, session: AsyncSession, proposal: ProposedChange) -> ProposalView:
        round_row = await session.get(ReviewRound, proposal.review_round_id)
        decision = await session.scalar(
            select(ReviewDecision).where(ReviewDecision.proposed_change_id == proposal.id)
        )
        assert round_row is not None
        document = await session.get(SuperDocsDocument, proposal.target_document_id)
        assert document is not None
        return ProposalView(
            proposal_id=proposal.id,
            review_round=round_row.ordinal,
            change_id=proposal.superdocs_change_id,
            operation=proposal.operation.value,
            chunk_id=proposal.chunk_id,
            document_id=document.session_document_id,
            old_html=proposal.old_html,
            new_html=proposal.new_html,
            ai_explanation=proposal.ai_explanation,
            replaces_proposal_id=proposal.replaces_proposal_id,
            decision=decision.decision if decision else None,
            feedback=decision.feedback if decision else None,
        )

    async def _current_round_context(
        self, session: AsyncSession, run: SyncRun
    ) -> tuple[ReviewRound, SuperDocsJob, SuperDocsSession]:
        if run.state is not SyncRunState.AWAITING_REVIEW:
            raise ReviewOperationInvalid("run is not awaiting review")
        job = await session.scalar(select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id))
        if job is None:
            raise RecoveryBlocked("run has no SuperDocs job")
        round_row = await session.scalar(
            select(ReviewRound)
            .where(
                ReviewRound.superdocs_job_id == job.id,
                ReviewRound.resolution.is_(None),
            )
            .order_by(ReviewRound.ordinal.desc())
        )
        if round_row is None:
            raise ReviewPayloadInvalid("run has no valid pending review round")
        superdocs_session = await self._session_for_run(session, run.id)
        return round_row, job, superdocs_session

    async def _review_effect(
        self,
        session: AsyncSession,
        run: SyncRun,
        round_row: ReviewRound,
        *,
        effect_type: EffectType = EffectType.SUPERDOCS_REVIEW_SUBMISSION,
    ) -> ExternalEffect:
        key = f"review-round:{round_row.id}"
        effect = await session.scalar(
            select(ExternalEffect).where(
                ExternalEffect.sync_run_id == run.id,
                ExternalEffect.effect_key == key,
            )
        )
        if effect is None:
            effect = ExternalEffect(
                sync_run_id=run.id,
                effect_key=key,
                effect_type=effect_type,
                outcome=EffectOutcome.NOT_STARTED,
                request_fingerprint="0" * 64,
                request_metadata={"review_round_id": str(round_row.id)},
                attempt_count=0,
            )
            session.add(effect)
            await session.flush()
        elif effect.effect_type is not effect_type:
            raise RecoveryBlocked("review effect kind does not match the pending gate")
        return effect

    async def _record_effect_error(
        self,
        run_id: UUID,
        *,
        effect_key: str,
        exc: SuperDocsRequestError,
        attention_code: str,
    ) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            effect = await self._effect_by_key(session, run.id, effect_key, for_update=True)
            if effect.outcome is EffectOutcome.SUCCEEDED:
                return
            if exc.outcome_unknown:
                if effect.outcome is EffectOutcome.STARTED:
                    require_effect_transition(effect.outcome, EffectOutcome.UNKNOWN)
                    effect.outcome = EffectOutcome.UNKNOWN
                elif effect.outcome is not EffectOutcome.UNKNOWN:
                    raise RecoveryBlocked("provider error did not match the effect checkpoint")
            else:
                if effect.outcome is EffectOutcome.UNKNOWN:
                    require_effect_transition(
                        effect.outcome,
                        EffectOutcome.NOT_STARTED,
                        reconciliation_evidence=True,
                    )
                else:
                    require_effect_transition(
                        effect.outcome,
                        EffectOutcome.NOT_STARTED,
                        definitive_non_occurrence=True,
                    )
                effect.outcome = EffectOutcome.NOT_STARTED
            effect.last_error = {
                "status_code": exc.status_code,
                "provider_request_id": exc.request_id,
                "retryable": exc.retryable,
                "outcome_unknown": exc.outcome_unknown,
            }
            run.failure_code = attention_code
            run.failure_detail = {"effect_key": effect_key, "outcome": effect.outcome.value}
            await session.commit()

    async def _quarantine_unresolved_effect(
        self,
        run_id: UUID,
        *,
        effect_key: str,
        attention_code: str,
    ) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            effect = await self._effect_by_key(session, run.id, effect_key, for_update=True)
            if effect.outcome is EffectOutcome.STARTED:
                if not _effect_lease_expired(effect):
                    return
                require_effect_transition(effect.outcome, EffectOutcome.UNKNOWN)
                effect.outcome = EffectOutcome.UNKNOWN
            elif effect.outcome is not EffectOutcome.UNKNOWN:
                return
            effect.reconciliation_evidence = {
                "same_session_external_state_found": False,
                "absence_treated_as_definitive_non_occurrence": False,
                "checked_at": datetime.now(UTC).isoformat(),
            }
            run.failure_code = attention_code
            run.failure_detail = {
                "effect_key": effect_key,
                "outcome": EffectOutcome.UNKNOWN.value,
                "automatic_retry_blocked": True,
            }
            await session.commit()

    async def _set_attention(self, run_id: UUID, code: str) -> None:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            run.failure_code = code
            run.failure_detail = {}
            await session.commit()

    async def _record_provider_read_error(self, run_id: UUID, exc: SuperDocsRequestError) -> None:
        code = (
            "SUPERDOCS_STATUS_READ_TIMEOUT"
            if exc.timed_out
            else "SUPERDOCS_STATUS_READ_UNAVAILABLE"
        )
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id, for_update=True)
            detail = dict(run.failure_detail or {})
            previous = detail.get("provider_read_error")
            previous_count = (
                previous.get("occurrence_count", 0) if isinstance(previous, dict) else 0
            )
            detail["provider_read_error"] = {
                "code": code,
                "operation": "jobs.get",
                "retryable": True,
                "observed_at": datetime.now(UTC).isoformat(),
                "occurrence_count": previous_count + 1,
                "provider_request_id": exc.request_id,
            }
            if run.failure_code is None or run.failure_code in _PROVIDER_READ_ATTENTION_CODES:
                run.failure_code = code
            run.failure_detail = detail
            await session.commit()

    async def _owned_document(self, session: AsyncSession, document_id: UUID) -> CloudDocument:
        document = await session.scalar(
            select(CloudDocument)
            .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
            .where(
                CloudDocument.id == document_id,
                CloudConnection.owner_subject == self._owner_subject,
            )
        )
        if document is None:
            raise SourceNotFound("registered source was not found")
        return document

    async def _owned_run(
        self, session: AsyncSession, run_id: UUID, *, for_update: bool = False
    ) -> SyncRun:
        statement = (
            select(SyncRun)
            .join(CloudDocument, CloudDocument.id == SyncRun.cloud_document_id)
            .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
            .where(
                SyncRun.id == run_id,
                CloudConnection.owner_subject == self._owner_subject,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        run = await session.scalar(statement)
        if run is None:
            raise RunNotFound("Phase 3 run was not found")
        return run

    @staticmethod
    async def _session_for_run(session: AsyncSession, run_id: UUID) -> SuperDocsSession:
        value = await session.scalar(
            select(SuperDocsSession).where(SuperDocsSession.sync_run_id == run_id)
        )
        if value is None:
            raise RecoveryBlocked("run has no persisted SuperDocs session")
        return value

    @staticmethod
    async def _snapshot_for_run(session: AsyncSession, run_id: UUID) -> SourceSnapshot:
        value = await session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.sync_run_id == run_id)
        )
        if value is None:
            raise RecoveryBlocked("run has no persisted source snapshot")
        return value

    @staticmethod
    async def _effect_by_key(
        session: AsyncSession, run_id: UUID, key: str, *, for_update: bool = False
    ) -> ExternalEffect:
        statement = select(ExternalEffect).where(
            ExternalEffect.sync_run_id == run_id,
            ExternalEffect.effect_key == key,
        )
        if for_update:
            statement = statement.with_for_update()
        effect = await session.scalar(statement)
        if effect is None:
            raise RecoveryBlocked("persisted external-effect checkpoint is missing")
        return effect

    def _transition(
        self,
        session: AsyncSession,
        run: SyncRun,
        target: SyncRunState,
        *,
        reason: str,
        sequence: int | None = None,
    ) -> None:
        if run.state is target:
            return
        transition = require_transition(run.state, target)
        run.state = target
        run.state_version += 1
        session.add(
            RunTransition(
                sync_run_id=run.id,
                sequence=sequence or run.state_version,
                from_state=transition.from_state,
                to_state=transition.to_state,
                actor_subject=self._owner_subject,
                reason=reason,
                evidence={},
            )
        )

    @staticmethod
    def _start_effect(effect: ExternalEffect) -> None:
        require_effect_transition(effect.outcome, EffectOutcome.STARTED)
        effect.outcome = EffectOutcome.STARTED
        effect.attempt_count += 1
        effect.started_at = datetime.now(UTC)
        effect.resolved_at = None
        effect.reconciliation_evidence = {}
        effect.last_error = None

    @staticmethod
    def _succeed_effect(effect: ExternalEffect) -> None:
        require_effect_transition(effect.outcome, EffectOutcome.SUCCEEDED)
        effect.outcome = EffectOutcome.SUCCEEDED
        effect.resolved_at = datetime.now(UTC)
        effect.last_error = None

    @classmethod
    def _complete_effect_success(cls, effect: ExternalEffect) -> None:
        if effect.outcome is EffectOutcome.SUCCEEDED:
            return
        if effect.outcome is EffectOutcome.UNKNOWN:
            cls._reconcile_effect_success(effect)
            return
        cls._succeed_effect(effect)

    @staticmethod
    def _reconcile_effect_success(effect: ExternalEffect) -> None:
        if effect.outcome is EffectOutcome.UNKNOWN:
            require_effect_transition(
                effect.outcome,
                EffectOutcome.SUCCEEDED,
                reconciliation_evidence=True,
            )
        elif effect.outcome is EffectOutcome.STARTED:
            require_effect_transition(effect.outcome, EffectOutcome.SUCCEEDED)
        else:
            raise RecoveryBlocked("effect was not awaiting reconciliation")
        effect.outcome = EffectOutcome.SUCCEEDED
        effect.resolved_at = datetime.now(UTC)
        effect.reconciliation_evidence = {"same_session_external_state_found": True}
        effect.last_error = None


def _target_identity(
    superdocs_session: SuperDocsSession, document: SuperDocsDocument
) -> SessionDocumentIdentity:
    return SessionDocumentIdentity(
        session_id=superdocs_session.session_id,
        session_document_id=document.session_document_id,
        durable_document_id=document.durable_document_id,
    )


def _effect_lease_expired(effect: ExternalEffect) -> bool:
    return effect.started_at is None or (
        _as_utc(effect.started_at) + SUPERDOCS_EFFECT_LEASE <= datetime.now(UTC)
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job_start_fingerprint(
    run: SyncRun, superdocs_session: SuperDocsSession, document: SuperDocsDocument
) -> str:
    return _hash_json(
        {
            "session_id": superdocs_session.session_id,
            "session_document_id": document.session_document_id,
            "instruction_sha256": run.rule_snapshot.get("instruction_sha256"),
            "approval_mode": "ask_every_time",
            "model_tier": run.rule_snapshot.get("model_tier"),
            "thinking_depth": run.rule_snapshot.get("thinking_depth"),
        }
    )


def _proposal_payload(change: PendingChange) -> dict[str, Any]:
    return {
        "change_id": change.change_id,
        "operation": change.operation.value,
        "chunk_id": change.chunk_id,
        "document_id": change.document_id,
        "old_html": change.old_html,
        "new_html": change.new_html,
        "ai_explanation": change.ai_explanation,
        "insert_after_chunk_id": change.insert_after_chunk_id,
        "safe_evidence": change.safe_evidence,
    }


def _export_view(export: SuperDocsExport | None) -> ExportView | None:
    if export is None:
        return None
    return ExportView(
        export_id=export.id,
        artifact_reference=export.artifact_reference,
        sha256=export.sha256,
        size_bytes=export.size_bytes,
        content_type=export.content_type,
        content_disposition=export.content_disposition,
        warnings=tuple(cast(dict[str, JsonValue], item) for item in export.warnings),
        final_version_id=export.final_version_id,
        exported_at=export.exported_at,
    )


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_optional_string(value: JsonValue | None) -> str | None:
    return value if isinstance(value, str) and value else None


_DEFINITIVE_RETRY_ATTENTION_CODES = frozenset(
    {
        "SUPERDOCS_UPLOAD_REJECTED",
        "SUPERDOCS_JOB_START_REJECTED",
        "SUPERDOCS_REVIEW_SUBMISSION_REJECTED",
        "SUPERDOCS_CONTINUE_REJECTED",
    }
)

_AUTOMATIC_RECOVERY_ATTENTION_CODES = (
    "SUPERDOCS_UPLOAD_OUTCOME_UNKNOWN",
    "SUPERDOCS_JOB_START_OUTCOME_UNKNOWN",
    "SUPERDOCS_FOCUS_OUTCOME_UNKNOWN",
)

_PROVIDER_READ_ATTENTION_CODES = frozenset(
    {"SUPERDOCS_STATUS_READ_TIMEOUT", "SUPERDOCS_STATUS_READ_UNAVAILABLE"}
)


def _provider_read_error_view(
    failure_detail: dict[str, JsonValue] | None,
) -> ProviderReadErrorView | None:
    if not failure_detail:
        return None
    value = failure_detail.get("provider_read_error")
    if not isinstance(value, dict):
        return None
    try:
        return ProviderReadErrorView.model_validate(value)
    except (TypeError, ValueError):
        return None


def _pending_batch_decisions_match(
    provider_decisions: dict[str, JsonValue],
    proposals: Sequence[ProposedChange],
    decisions: Sequence[ReviewDecision],
) -> bool:
    proposal_by_id = {proposal.id: proposal for proposal in proposals}
    if len(decisions) != len(proposals):
        return False
    for decision in decisions:
        proposal = proposal_by_id.get(decision.proposed_change_id)
        if proposal is None:
            return False
        provider_value = provider_decisions.get(proposal.superdocs_change_id)
        if not isinstance(provider_value, dict):
            return False
        expected_approved = decision.decision is ChangeDecision.APPROVE
        if provider_value.get("approved") is not expected_approved:
            return False
        if decision.feedback is not None and provider_value.get("feedback") != decision.feedback:
            return False
    return True
