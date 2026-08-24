from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docrelay.core.config import Settings
from docrelay.domain.enums import (
    ChangeDecision,
    ConflictChoice,
    EffectOutcome,
    ReviewAwaitingKind,
    SyncRunState,
    VerificationStatus,
    WatchItemOutcome,
    WatchScanStatus,
    WatchScanTrigger,
    WriteAuthorizationState,
)
from docrelay.integrations.google.contracts import GoogleWriteBackPort
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.integrations.superdocs.runtime import SuperDocsRuntime
from docrelay.persistence.database import Database
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    ExternalEffect,
    ProposedChange,
    ReviewDecision,
    ReviewRound,
    SuperDocsExport,
    SuperDocsJob,
    SyncRun,
    VerificationResult,
    WatchConfig,
    WatchDocumentVersion,
    WatchRunLink,
    WatchScan,
    WatchScanItem,
    WriteConflict,
    WritePlan,
)
from docrelay.services.artifacts import ArtifactStore
from docrelay.services.superdocs_workflow import (
    DecisionInput,
    ExportArtifactView,
    ExportView,
    ProposalView,
    RunNotFound,
    RunView,
    SuperDocsNotConfigured,
    SuperDocsWorkflow,
    get_write_back_summary,
)
from docrelay.services.watch import WatchNotFound, WatchService, build_watch_service
from docrelay.services.write_planning import DryRunView, WritePlanningService
from docrelay.services.writeback import WriteBackService, WriteBackView


class ReviewStatus(StrEnum):
    NOT_READY = "NOT_READY"
    AWAITING_DECISIONS = "AWAITING_DECISIONS"
    AWAITING_CONTINUE = "AWAITING_CONTINUE"
    DECISIONS_SUBMITTED = "DECISIONS_SUBMITTED"
    REVIEWED = "REVIEWED"
    FAILED = "FAILED"


class DryRunSummaryStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    READY = "READY"


class MachineWriteBackStatus(StrEnum):
    NOT_READY = "NOT_READY"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    WRITE_AUTHORIZATION_REQUIRED = "WRITE_AUTHORIZATION_REQUIRED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    WRITE_VERIFIED = "WRITE_VERIFIED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"
    ATTENTION = "ATTENTION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REVIEW_LATEST = "REVIEW_LATEST"


class MachineModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConflictSummary(MachineModel):
    detection_stage: str
    baseline_revision_id: str
    latest_revision_id: str | None
    decision: ConflictChoice | None


class RunSummary(MachineModel):
    run_id: UUID
    watch_id: UUID | None
    originating_scan_id: UUID | None
    source_id: UUID
    provider_file_id: str
    document_name: str
    instruction: str | None
    proposal_count: int
    provider_version: str | None
    source_revision_id: str
    matched_rule_id: UUID | None
    matched_rule_version: int | None
    workflow_state: SyncRunState
    review_status: ReviewStatus
    write_authorization_status: WriteAuthorizationState | None
    dry_run_status: DryRunSummaryStatus
    write_back_status: MachineWriteBackStatus
    verification_status: VerificationStatus | None
    last_error_code: str | None
    conflict: ConflictSummary | None
    ready_for_dry_run: bool
    ready_for_write_back: bool
    export: ExportView | None
    started_at: datetime | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    external_effect_count: int
    external_effect_attempt_count: int
    external_effects_unknown: int
    superdocs_usage: dict[str, JsonValue]


class ScanItemView(MachineModel):
    provider_file_id: str
    provider_version: str | None
    name: str
    mime_type: str
    ancestor_folder_ids: tuple[str, ...]
    discovery_kind: str
    outcome: WatchItemOutcome
    reason_code: str | None
    matched_rule_id: UUID | None
    matched_rule_version: int | None
    run_id: UUID | None
    run_created_in_scan: bool


class ScanView(MachineModel):
    scan_id: UUID
    watch_id: UUID
    trigger: WatchScanTrigger
    status: WatchScanStatus
    claim_generation: int
    started_at: datetime
    completed_at: datetime | None
    discovered_count: int
    changed_count: int
    unchanged_count: int
    enqueued_count: int
    skipped_count: int
    failed_count: int
    failure_code: str | None
    items: tuple[ScanItemView, ...]
    runs: tuple[RunSummary, ...]


class MultiDocumentQueryService:
    """Read-only composition over durable watch, run, review, plan, and write records."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        owner_subject: str,
    ) -> None:
        self._sessions = sessions
        self._owner_subject = owner_subject

    async def get_run_summary(self, run_id: UUID) -> RunSummary:
        async with self._sessions() as session:
            run = await self._owned_run(session, run_id)
            return await self._summary(session, run)

    async def list_runs(self) -> tuple[RunSummary, ...]:
        """Return every owned run, newest first, without changing workflow state."""
        async with self._sessions() as session:
            runs = (
                await session.scalars(
                    select(SyncRun)
                    .join(CloudDocument, CloudDocument.id == SyncRun.cloud_document_id)
                    .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
                    .where(CloudConnection.owner_subject == self._owner_subject)
                    .order_by(SyncRun.updated_at.desc(), SyncRun.id.desc())
                )
            ).all()
            return tuple([await self._summary(session, run) for run in runs])

    async def list_watch_runs(self, watch_id: UUID) -> tuple[RunSummary, ...]:
        async with self._sessions() as session:
            await self._owned_watch(session, watch_id)
            runs = (
                await session.scalars(
                    select(SyncRun)
                    .join(WatchRunLink, WatchRunLink.sync_run_id == SyncRun.id)
                    .where(WatchRunLink.watch_config_id == watch_id)
                    .order_by(SyncRun.created_at, SyncRun.id)
                )
            ).all()
            return tuple([await self._summary(session, run) for run in runs])

    async def list_scan_runs(self, scan_id: UUID) -> tuple[RunSummary, ...]:
        async with self._sessions() as session:
            await self._owned_scan(session, scan_id)
            runs = (
                await session.scalars(
                    select(SyncRun)
                    .join(WatchRunLink, WatchRunLink.sync_run_id == SyncRun.id)
                    .where(WatchRunLink.watch_scan_id == scan_id)
                    .order_by(SyncRun.created_at, SyncRun.id)
                )
            ).all()
            return tuple([await self._summary(session, run) for run in runs])

    async def get_scan(self, scan_id: UUID) -> ScanView:
        async with self._sessions() as session:
            scan = await self._owned_scan(session, scan_id)
            rows = (
                await session.scalars(
                    select(WatchScanItem)
                    .where(WatchScanItem.watch_scan_id == scan.id)
                    .order_by(WatchScanItem.provider_file_id)
                )
            ).all()
            runs = (
                await session.scalars(
                    select(SyncRun)
                    .join(WatchRunLink, WatchRunLink.sync_run_id == SyncRun.id)
                    .where(WatchRunLink.watch_scan_id == scan.id)
                    .order_by(SyncRun.created_at, SyncRun.id)
                )
            ).all()
            summaries = tuple([await self._summary(session, run) for run in runs])
            created_run_ids = {run.run_id for run in summaries}
            return ScanView(
                scan_id=scan.id,
                watch_id=scan.watch_config_id,
                trigger=scan.trigger,
                status=scan.status,
                claim_generation=scan.claim_generation,
                started_at=scan.started_at,
                completed_at=scan.completed_at,
                discovered_count=scan.discovered_count,
                changed_count=scan.changed_count,
                unchanged_count=scan.unchanged_count,
                enqueued_count=scan.enqueued_count,
                skipped_count=scan.skipped_count,
                failed_count=scan.failed_count,
                failure_code=scan.failure_code,
                items=tuple(
                    ScanItemView(
                        provider_file_id=row.provider_file_id,
                        provider_version=row.provider_version,
                        name=row.display_name,
                        mime_type=row.mime_type,
                        ancestor_folder_ids=tuple(row.ancestor_folder_ids),
                        discovery_kind=row.discovery_kind,
                        outcome=row.outcome,
                        reason_code=row.reason_code,
                        matched_rule_id=row.matched_rule_id,
                        matched_rule_version=row.matched_rule_version,
                        run_id=row.sync_run_id,
                        run_created_in_scan=row.sync_run_id in created_run_ids,
                    )
                    for row in rows
                ),
                runs=summaries,
            )

    async def _owned_watch(self, session: AsyncSession, watch_id: UUID) -> WatchConfig:
        watch = await session.scalar(
            select(WatchConfig)
            .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
            .where(
                WatchConfig.id == watch_id,
                CloudConnection.owner_subject == self._owner_subject,
            )
        )
        if watch is None:
            raise WatchNotFound("watch root was not found")
        return watch

    async def _owned_scan(self, session: AsyncSession, scan_id: UUID) -> WatchScan:
        scan = await session.scalar(
            select(WatchScan)
            .join(WatchConfig, WatchConfig.id == WatchScan.watch_config_id)
            .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
            .where(
                WatchScan.id == scan_id,
                CloudConnection.owner_subject == self._owner_subject,
            )
        )
        if scan is None:
            raise WatchNotFound("watch scan was not found")
        return scan

    async def _owned_run(self, session: AsyncSession, run_id: UUID) -> SyncRun:
        run = await session.scalar(
            select(SyncRun)
            .join(CloudDocument, CloudDocument.id == SyncRun.cloud_document_id)
            .join(CloudConnection, CloudConnection.id == CloudDocument.connection_id)
            .where(
                SyncRun.id == run_id,
                CloudConnection.owner_subject == self._owner_subject,
            )
        )
        if run is None:
            raise RunNotFound("run was not found")
        return run

    async def _summary(self, session: AsyncSession, run: SyncRun) -> RunSummary:
        document = await session.get(CloudDocument, run.cloud_document_id)
        assert document is not None
        link = await session.scalar(select(WatchRunLink).where(WatchRunLink.sync_run_id == run.id))
        version = (
            await session.get(WatchDocumentVersion, link.watch_document_version_id)
            if link is not None
            else None
        )
        origin_item = (
            await session.scalar(
                select(WatchScanItem).where(
                    WatchScanItem.watch_scan_id == link.watch_scan_id,
                    WatchScanItem.sync_run_id == run.id,
                )
            )
            if link is not None
            else None
        )
        review_round = await session.scalar(
            select(ReviewRound)
            .where(ReviewRound.sync_run_id == run.id, ReviewRound.resolution.is_(None))
            .order_by(ReviewRound.ordinal.desc())
        )
        decisions = (
            await session.scalars(
                select(ReviewDecision).where(ReviewDecision.sync_run_id == run.id)
            )
        ).all()
        proposal_count = await session.scalar(
            select(func.count(ProposedChange.id)).where(ProposedChange.sync_run_id == run.id)
        )
        plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run.id))
        export = await session.scalar(
            select(SuperDocsExport).where(SuperDocsExport.sync_run_id == run.id)
        )
        verification = await session.scalar(
            select(VerificationResult)
            .where(VerificationResult.sync_run_id == run.id)
            .order_by(VerificationResult.created_at.desc())
        )
        conflict = await session.scalar(
            select(WriteConflict).where(WriteConflict.sync_run_id == run.id)
        )
        effects = (
            await session.scalars(
                select(ExternalEffect).where(ExternalEffect.sync_run_id == run.id)
            )
        ).all()
        job = await session.scalar(select(SuperDocsJob).where(SuperDocsJob.sync_run_id == run.id))
        write_back = await get_write_back_summary(session, run)
        review_status = _review_status(run, review_round, bool(decisions), export is not None)
        authorization = link.write_authorization_state if link is not None else None
        write_back_status = _machine_write_status(
            run=run,
            plan_exists=plan is not None,
            authorization=authorization,
            persisted_status=write_back.status if write_back is not None else None,
        )
        duration_ms = None
        if run.started_at is not None and run.finished_at is not None:
            duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
        export_view = None
        if export is not None:
            export_view = ExportView(
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
        return RunSummary(
            run_id=run.id,
            watch_id=link.watch_config_id if link is not None else None,
            originating_scan_id=link.watch_scan_id if link is not None else None,
            source_id=run.cloud_document_id,
            provider_file_id=document.provider_file_id,
            document_name=(
                origin_item.display_name
                if origin_item is not None
                else document.display_name or "Google document"
            ),
            instruction=(
                instruction
                if isinstance((instruction := run.rule_snapshot.get("instruction")), str)
                else None
            ),
            proposal_count=proposal_count or 0,
            provider_version=version.provider_version if version is not None else None,
            source_revision_id=run.baseline_revision_id or "",
            matched_rule_id=run.folder_rule_id,
            matched_rule_version=run.folder_rule_version,
            workflow_state=run.state,
            review_status=review_status,
            write_authorization_status=authorization,
            dry_run_status=(
                DryRunSummaryStatus.READY if plan is not None else DryRunSummaryStatus.NOT_REQUESTED
            ),
            write_back_status=write_back_status,
            verification_status=verification.status if verification is not None else None,
            last_error_code=run.failure_code,
            conflict=(
                ConflictSummary(
                    detection_stage=conflict.detection_stage,
                    baseline_revision_id=conflict.baseline_revision_id,
                    latest_revision_id=conflict.latest_revision_id,
                    decision=conflict.decision,
                )
                if conflict is not None
                else None
            ),
            ready_for_dry_run=(
                run.state is SyncRunState.REVIEWED_EXPORT_READY
                and export is not None
                and not export.warnings
                and any(decision.decision is ChangeDecision.APPROVE for decision in decisions)
            ),
            ready_for_write_back=(
                plan is not None
                and authorization is not WriteAuthorizationState.REQUIRED
                and write_back_status is MachineWriteBackStatus.READY
            ),
            export=export_view,
            started_at=run.started_at,
            created_at=run.created_at,
            updated_at=run.updated_at,
            finished_at=run.finished_at,
            duration_ms=duration_ms,
            external_effect_count=len(effects),
            external_effect_attempt_count=sum(effect.attempt_count for effect in effects),
            external_effects_unknown=sum(
                effect.outcome is EffectOutcome.UNKNOWN for effect in effects
            ),
            superdocs_usage=(
                cast(dict[str, JsonValue], dict(job.usage_evidence)) if job is not None else {}
            ),
        )


class MachineOperations:
    """One application-service facade shared by REST and MCP adapters."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        artifacts: ArtifactStore,
        google_runtime: GoogleRuntime | None,
        superdocs_runtime: SuperDocsRuntime | None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.artifacts = artifacts
        self.google_runtime = google_runtime
        self.superdocs_runtime = superdocs_runtime

    @property
    def queries(self) -> MultiDocumentQueryService:
        return MultiDocumentQueryService(
            sessions=self.database.sessions,
            owner_subject=self.settings.docrelay_owner_subject,
        )

    def runs(self) -> SuperDocsWorkflow:
        if self.superdocs_runtime is None:
            raise SuperDocsNotConfigured("SuperDocs is not configured on this server")
        return SuperDocsWorkflow(
            sessions=self.database.sessions,
            superdocs=self.superdocs_runtime.client,
            artifacts=self.artifacts,
            owner_subject=self.settings.docrelay_owner_subject,
        )

    def watch(self) -> WatchService:
        if self.google_runtime is None:
            raise GoogleIntegrationError(
                GoogleErrorCode.OAUTH_NOT_CONFIGURED,
                "Google OAuth is not configured on this server",
            )
        return build_watch_service(
            sessions=self.database.sessions,
            owner_subject=self.settings.docrelay_owner_subject,
            runtime=self.google_runtime,
            runs=self.runs(),
            state_ttl_seconds=self.settings.google_oauth_state_ttl_seconds,
            refresh_skew_seconds=self.settings.google_access_token_refresh_skew_seconds,
            baseline_max_attempts=self.settings.google_baseline_max_attempts,
            scan_lease_seconds=self.settings.watch_scan_lease_seconds,
            max_items_per_scan=self.settings.watch_max_items_per_scan,
        )

    def planning(self) -> WritePlanningService:
        return WritePlanningService(
            sessions=self.database.sessions,
            owner_subject=self.settings.docrelay_owner_subject,
            artifacts=self.artifacts,
        )

    def write_service(self) -> WriteBackService:
        runtime = self.google_runtime
        if runtime is None or runtime.write_client_factory is None:
            raise SuperDocsNotConfigured("Google write-back is not configured on this server")

        async def provider_factory(
            session: AsyncSession, connection_id: UUID
        ) -> GoogleWriteBackPort:
            google = GoogleConnectionService(
                session=session,
                runtime=runtime,
                owner_subject=self.settings.docrelay_owner_subject,
                state_ttl_seconds=self.settings.google_oauth_state_ttl_seconds,
                refresh_skew_seconds=self.settings.google_access_token_refresh_skew_seconds,
                baseline_max_attempts=self.settings.google_baseline_max_attempts,
            )
            return await google.write_client(connection_id)

        return WriteBackService(
            sessions=self.database.sessions,
            owner_subject=self.settings.docrelay_owner_subject,
            provider_factory=provider_factory,
            artifacts=self.artifacts,
        )

    async def get_run(self, run_id: UUID) -> RunView:
        return await self.runs().get_run(run_id)

    async def get_run_summary(self, run_id: UUID) -> RunSummary:
        return await self.queries.get_run_summary(run_id)

    async def list_run_summaries(self) -> tuple[RunSummary, ...]:
        # Keep the REST machine surface unavailable when its workflow runtime is
        # not configured, matching the existing run endpoints.
        self.runs()
        return await self.queries.list_runs()

    async def resume_run(self, run_id: UUID, *, allow_definitive_retry: bool = False) -> RunView:
        return await self.runs().resume(run_id, allow_definitive_retry=allow_definitive_retry)

    async def list_proposals(self, run_id: UUID) -> tuple[ProposalView, ...]:
        return await self.runs().list_proposals(run_id)

    async def submit_review_decisions(
        self, run_id: UUID, decisions: tuple[DecisionInput, ...]
    ) -> RunView:
        return await self.runs().submit_decisions(
            run_id,
            decisions=decisions,
            reviewer_subject=self.settings.docrelay_owner_subject,
        )

    async def submit_continue(self, run_id: UUID, *, should_continue: bool) -> RunView:
        return await self.runs().submit_continue(
            run_id,
            should_continue=should_continue,
            reviewer_subject=self.settings.docrelay_owner_subject,
        )

    async def create_dry_run(self, run_id: UUID, *, proposal_id: UUID | None = None) -> DryRunView:
        return await self.planning().dry_run(run_id, proposal_id=proposal_id)

    async def write_back(self, run_id: UUID) -> WriteBackView:
        return await self.write_service().execute(run_id)

    async def decide_write_conflict(self, run_id: UUID, *, choice: ConflictChoice) -> WriteBackView:
        return await self.write_service().decide_conflict(run_id, choice)

    async def verify_write_authorization(
        self, run_id: UUID, *, picker_file_id: str
    ) -> WatchRunLink:
        return await self.watch().verify_run_write_authorization(
            run_id, picker_file_id=picker_file_id
        )

    async def get_export(self, run_id: UUID) -> ExportArtifactView:
        return await self.runs().get_export_artifact(run_id)


def _review_status(
    run: SyncRun,
    review_round: ReviewRound | None,
    has_decisions: bool,
    has_export: bool,
) -> ReviewStatus:
    if has_export:
        return ReviewStatus.REVIEWED
    if run.state is SyncRunState.AWAITING_REVIEW and review_round is not None:
        if review_round.awaiting_kind is ReviewAwaitingKind.CHANGE_BATCH:
            return ReviewStatus.AWAITING_DECISIONS
        return ReviewStatus.AWAITING_CONTINUE
    if has_decisions:
        return ReviewStatus.DECISIONS_SUBMITTED
    if run.state in {
        SyncRunState.FAILED,
        SyncRunState.CANCELLED,
        SyncRunState.UNSUPPORTED,
        SyncRunState.EXPIRED,
    }:
        return ReviewStatus.FAILED
    return ReviewStatus.NOT_READY


def _machine_write_status(
    *,
    run: SyncRun,
    plan_exists: bool,
    authorization: WriteAuthorizationState | None,
    persisted_status: str | None,
) -> MachineWriteBackStatus:
    if not plan_exists:
        if run.state is SyncRunState.AWAITING_REVIEW:
            return MachineWriteBackStatus.AWAITING_REVIEW
        return MachineWriteBackStatus.NOT_READY
    if run.state is SyncRunState.COMMIT_OUTCOME_UNKNOWN:
        return MachineWriteBackStatus.UNKNOWN
    if authorization is WriteAuthorizationState.REQUIRED:
        return MachineWriteBackStatus.WRITE_AUTHORIZATION_REQUIRED
    if persisted_status is None:
        return MachineWriteBackStatus.READY
    return MachineWriteBackStatus(persisted_status)
