import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from docrelay.domain.enums import (
    ChangeDecision,
    ConnectionStatus,
    EffectOutcome,
    EffectType,
    Provider,
    ReviewRoundResolution,
    SuperDocsJobStatus,
    SyncRunState,
)
from docrelay.integrations.superdocs.client import SuperDocsRequestError
from docrelay.integrations.superdocs.contracts import (
    ChangeReviewDecision,
    ContinueReceipt,
    ExportArtifact,
    FocusedDocument,
    IngestedDocument,
    JobReference,
    JobSnapshot,
    PendingChange,
    ReviewReceipt,
    SessionDocument,
    SessionDocumentIdentity,
)
from docrelay.persistence.base import Base
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
)
from docrelay.services.artifacts import ArtifactStore, InMemoryArtifactStore
from docrelay.services.superdocs_workflow import (
    DecisionInput,
    IncompleteDecisionSet,
    RecoveryBlocked,
    ReviewOperationInvalid,
    ReviewPayloadInvalid,
    SuperDocsBaseline,
    SuperDocsWorkflow,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class FakeSuperDocs:
    def __init__(self) -> None:
        self.upload_calls = 0
        self.start_calls = 0
        self.decision_calls: list[tuple[ChangeReviewDecision, ...]] = []
        self.continue_calls: list[bool] = []
        self.focus_calls: list[str] = []
        self.export_calls = 0
        self.session_id: str | None = None
        self.job_id = "job-existing-1"
        self.start_loses_response = False
        self.upload_loses_response = False
        self.hide_upload_from_roster = False
        self.hide_job_from_roster = False
        self.upload_rejects = False
        self.decision_loses_response = False
        self.continue_loses_response = False
        self.export_times_out_once = False
        self._export_timed_out = False
        self.block_upload: asyncio.Event | None = None
        self.upload_entered = asyncio.Event()
        self.block_start: asyncio.Event | None = None
        self.start_entered = asyncio.Event()
        self.block_job_read: asyncio.Event | None = None
        self.job_read_entered = asyncio.Event()
        self.job_read_calls = 0
        self.job_read_timeouts_remaining = 0
        self.job = self.processing_job()

    def processing_job(self) -> JobSnapshot:
        session_id = self.session_id or "not-started"
        return JobSnapshot(
            reference=JobReference(
                job_id=self.job_id,
                session_id=session_id,
                status=SuperDocsJobStatus.IN_PROGRESS,
            ),
            progress=45,
            safe_metadata={"job_type": "chat"},
        )

    def review_job(
        self,
        *changes: PendingChange,
        awaiting_kind: str | None = None,
        pending_batch_decisions: dict[str, Any] | None = None,
    ) -> JobSnapshot:
        assert self.session_id is not None
        return JobSnapshot(
            reference=JobReference(
                job_id=self.job_id,
                session_id=self.session_id,
                status=SuperDocsJobStatus.AWAITING_APPROVAL,
            ),
            awaiting_kind=awaiting_kind,
            pending_changes=tuple(changes),
            pending_batch_decisions=pending_batch_decisions or {},
            progress=50,
            safe_metadata={"job_type": "chat"},
        )

    def completed_job(self) -> JobSnapshot:
        assert self.session_id is not None
        return JobSnapshot(
            reference=JobReference(
                job_id=self.job_id,
                session_id=self.session_id,
                status=SuperDocsJobStatus.COMPLETED,
            ),
            progress=100,
            final_version_id="final-version-1",
            updated_html_sha256=_sha(b"<p>30 days</p>"),
            final_change_statuses={"replacement-1": "approved"},
            usage={"was_billable": True, "ops_charged": 1},
            safe_metadata={"job_type": "chat"},
        )

    async def upload_docx(
        self, *, docx_bytes: bytes, filename: str, session_id: str, open_mode: str = "replace"
    ) -> IngestedDocument:
        self.upload_entered.set()
        if self.block_upload is not None:
            await self.block_upload.wait()
        self.upload_calls += 1
        self.session_id = session_id
        self.job = self.processing_job()
        if self.upload_loses_response:
            self.upload_loses_response = False
            raise SuperDocsRequestError("upload outcome is unknown", outcome_unknown=True)
        if self.upload_rejects:
            self.upload_rejects = False
            raise SuperDocsRequestError(
                "upload was rejected", outcome_unknown=False, status_code=401
            )
        return IngestedDocument(
            identity=SessionDocumentIdentity(
                session_id=session_id,
                session_document_id="doc_primary",
            ),
            upload_version_id="upload-version-1",
            baseline_html_sha256=_sha(b'<p data-chunk-id="fresh-1">45 days</p>'),
            chunks_count=1,
            safe_evidence={"persisted": True},
        )

    async def list_session_documents(
        self, session_id: str, *, include_html: bool = False
    ) -> tuple[SessionDocument, ...]:
        if self.upload_calls == 0 or self.hide_upload_from_roster:
            return ()
        return (
            SessionDocument(
                identity=SessionDocumentIdentity(
                    session_id=session_id,
                    session_document_id="doc_primary",
                    durable_document_id="durable-document-1",
                ),
                title="baseline.docx",
                focused=True,
                chunks_count=1,
                version_id="upload-version-1",
                html_sha256=(
                    _sha(b'<p data-chunk-id="fresh-1">45 days</p>') if include_html else None
                ),
                safe_evidence={},
            ),
        )

    async def start_edit(
        self,
        *,
        target: SessionDocumentIdentity,
        instruction: str,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
    ) -> JobReference:
        self.start_entered.set()
        if self.block_start is not None:
            await self.block_start.wait()
        self.start_calls += 1
        self.session_id = target.session_id
        self.job = self.processing_job()
        if self.start_loses_response:
            self.start_loses_response = False
            raise SuperDocsRequestError("request outcome is unknown", outcome_unknown=True)
        return self.job.reference

    async def get_job(self, job_id: str) -> JobSnapshot:
        assert job_id == self.job_id
        self.job_read_calls += 1
        if self.job_read_timeouts_remaining:
            self.job_read_timeouts_remaining -= 1
            raise SuperDocsRequestError(
                "SuperDocs request timed out",
                outcome_unknown=False,
                retryable=True,
                timed_out=True,
            )
        observed = self.job
        self.job_read_entered.set()
        if self.block_job_read is not None:
            await self.block_job_read.wait()
        return observed

    async def recover_session_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]:
        if self.start_calls == 0 or self.hide_job_from_roster:
            return ()
        assert session_id == self.session_id
        return (self.job,)

    async def submit_decisions(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: tuple[ChangeReviewDecision, ...],
    ) -> ReviewReceipt:
        self.decision_calls.append(decisions)
        self.job = self.processing_job()
        if self.decision_loses_response:
            self.decision_loses_response = False
            raise SuperDocsRequestError(
                "review submission outcome is unknown", outcome_unknown=True
            )
        return ReviewReceipt(status="ok", batch_complete=True, safe_evidence={})

    async def submit_continue(
        self, *, session_id: str, job_id: str, should_continue: bool
    ) -> ContinueReceipt:
        self.continue_calls.append(should_continue)
        self.job = self.processing_job()
        if self.continue_loses_response:
            self.continue_loses_response = False
            raise SuperDocsRequestError("continue outcome is unknown", outcome_unknown=True)
        return ContinueReceipt(status="ok", safe_evidence={})

    async def focus_document(self, target: SessionDocumentIdentity) -> FocusedDocument:
        self.focus_calls.append(target.session_document_id)
        return FocusedDocument(
            identity=target,
            focused=True,
            version_id="final-version-1",
            safe_evidence={},
        )

    async def export_docx(
        self, *, target: SessionDocumentIdentity, filename: str
    ) -> ExportArtifact:
        self.export_calls += 1
        if self.export_times_out_once and not self._export_timed_out:
            self._export_timed_out = True
            raise SuperDocsRequestError("export outcome unknown", outcome_unknown=True)
        content = b"PK\x03\x04reviewed document contains 30 days"
        return ExportArtifact(
            docx_bytes=content,
            sha256=_sha(content),
            size_bytes=len(content),
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            content_disposition='attachment; filename="reviewed.docx"',
            warnings=(),
        )


@pytest.fixture
async def workflow_database() -> AsyncIterator[
    tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        connection = CloudConnection(
            owner_subject="owner-1",
            provider=Provider.GOOGLE,
            provider_account_subject="principal-1",
            status=ConnectionStatus.CONNECTED,
            granted_scopes={"scopes": ["openid", "drive.file"]},
        )
        session.add(connection)
        await session.flush()
        document = CloudDocument(
            connection_id=connection.id,
            provider_file_id="google-file-1",
            mime_type="application/vnd.google-apps.document",
            display_name="Synthetic agreement",
            parent_ids=["parent-1"],
            last_seen_revision_id="revision-A",
        )
        session.add(document)
        await session.commit()
        document_id = document.id
    yield engine, sessions, document_id
    await engine.dispose()


def baseline(document_id: UUID, revision: str = "revision-A") -> SuperDocsBaseline:
    docx = f"PK\x03\x04synthetic baseline {revision} with 45 days".encode()
    return SuperDocsBaseline(
        cloud_document_id=document_id,
        provider_revision_id=revision,
        source_format="application/vnd.google-apps.document",
        captured_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        native_raw_sha256="0" * 64,
        native_canonical_sha256="1" * 64,
        exported_docx_sha256=_sha(docx),
        canonical_schema_version="docrelay.google-native-canonical.v1",
        capability_evidence={"can_modify_content": True},
        provider_evidence={"revision_before": revision, "revision_after": revision},
        docx_bytes=docx,
        filename="synthetic-baseline.docx",
    )


def proposal(
    change_id: str,
    chunk_id: str,
    old: str,
    new: str,
    explanation: str,
) -> PendingChange:
    return PendingChange(
        change_id=change_id,
        operation="edit",
        document_id="doc_primary",
        chunk_id=chunk_id,
        old_html=old,
        new_html=new,
        ai_explanation=explanation,
        safe_evidence={},
    )


class CorruptingArtifactStore(ArtifactStore):
    def __init__(self) -> None:
        self._stored: dict[str, bytes] = {}

    async def put(self, reference: str, content: bytes, expected_sha256: str) -> None:
        assert hashlib.sha256(content).hexdigest() == expected_sha256
        self._stored[reference] = content

    async def read(self, reference: str) -> bytes:
        assert reference in self._stored
        return b"tampered artifact bytes"


async def test_in_flight_upload_and_job_start_are_not_retried_by_concurrent_resume(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.block_upload = asyncio.Event()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )

    first = asyncio.create_task(
        service.start_run(
            baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
        )
    )
    await asyncio.wait_for(provider.upload_entered.wait(), timeout=5)
    async with sessions() as session:
        run_id = await session.scalar(select(SyncRun.id))
    assert run_id is not None

    during_upload = await asyncio.wait_for(service.resume(run_id), timeout=5)
    assert during_upload.state is SyncRunState.EDITING
    assert provider.upload_calls == 0

    provider.block_upload.set()
    provider.block_start = asyncio.Event()
    await asyncio.wait_for(provider.start_entered.wait(), timeout=5)
    during_start = await asyncio.wait_for(service.resume(run_id), timeout=5)
    assert during_start.provider_job_id is None
    assert provider.start_calls == 0

    provider.block_start.set()
    completed_start = await asyncio.wait_for(first, timeout=5)
    assert completed_start.provider_job_id == provider.job_id
    assert provider.upload_calls == 1
    assert provider.start_calls == 1


async def test_jobs_get_timeouts_remain_recoverable_and_retry_only_the_status_read(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    provider.job_read_timeouts_remaining = 2

    first = await service.resume(started.run_id)
    second = await service.resume(started.run_id)

    assert first.state is SyncRunState.EDITING
    assert second.state is SyncRunState.EDITING
    assert first.attention_code == "SUPERDOCS_STATUS_READ_TIMEOUT"
    assert second.provider_read_error is not None
    assert second.provider_read_error.operation == "jobs.get"
    assert second.provider_read_error.occurrence_count == 2
    assert provider.job_read_calls == 2
    assert provider.upload_calls == 1
    assert provider.start_calls == 1
    assert provider.decision_calls == []
    assert provider.continue_calls == []
    assert provider.focus_calls == []
    assert provider.export_calls == 0

    async with sessions() as session:
        run = await session.get(SyncRun, started.run_id)
        effects = tuple(
            await session.scalars(
                select(ExternalEffect).where(ExternalEffect.sync_run_id == started.run_id)
            )
        )
    assert run is not None and run.state is SyncRunState.EDITING
    assert all(
        effect.effect_type not in {EffectType.GOOGLE_BACKUP_COPY, EffectType.GOOGLE_BATCH_UPDATE}
        for effect in effects
    )
    assert sum(effect.attempt_count for effect in effects) == 2

    recovered = await service.resume(started.run_id)

    assert recovered.state is SyncRunState.EDITING
    assert recovered.attention_code is None
    assert recovered.provider_read_error is None
    assert provider.job_read_calls == 3
    assert provider.upload_calls == 1
    assert provider.start_calls == 1
    assert provider.focus_calls == []
    assert provider.export_calls == 0

    provider.job = provider.review_job(
        proposal(
            "replacement-1",
            "chunk-1",
            "<p>Payment is due within 45 days.</p>",
            "<p>Payment is due within 30 days.</p>",
            "Shorten the payment term.",
        )
    )
    awaiting = await service.resume(started.run_id)
    assert awaiting.state is SyncRunState.AWAITING_REVIEW
    assert awaiting.provider_read_error is None
    assert provider.upload_calls == 1
    assert provider.start_calls == 1
    assert provider.decision_calls == []


async def test_jobs_get_timeout_does_not_erase_existing_unknown_attention(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    async with sessions() as session:
        run = await session.get(SyncRun, started.run_id)
        assert run is not None
        run.failure_code = "SUPERDOCS_REVIEW_SUBMISSION_OUTCOME_UNKNOWN"
        run.failure_detail = {"effect_key": "review-round:preserved", "outcome": "UNKNOWN"}
        await session.commit()
    provider.job_read_timeouts_remaining = 1

    delayed = await service.resume(started.run_id)

    assert delayed.state is SyncRunState.EDITING
    assert delayed.attention_code == "SUPERDOCS_REVIEW_SUBMISSION_OUTCOME_UNKNOWN"
    assert delayed.provider_read_error is not None
    assert delayed.provider_read_error.code == "SUPERDOCS_STATUS_READ_TIMEOUT"
    async with sessions() as session:
        run = await session.get(SyncRun, started.run_id)
    assert run is not None
    assert run.failure_detail is not None
    assert run.failure_detail["effect_key"] == "review-round:preserved"
    assert run.failure_detail["outcome"] == "UNKNOWN"


async def test_baseline_artifact_is_rehashed_before_superdocs_upload(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=CorruptingArtifactStore(),
        owner_subject="owner-1",
    )

    with pytest.raises(RecoveryBlocked, match="immutable identity"):
        await service.start_run(
            baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
        )

    assert provider.upload_calls == 0
    async with sessions() as session:
        run = await session.scalar(select(SyncRun))
    assert run is not None
    assert run.failure_code == "SUPERDOCS_BASELINE_ARTIFACT_INTEGRITY_FAILED"


async def test_lost_start_response_recovers_same_job_without_duplicate_paid_start(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.start_loses_response = True
    artifacts = InMemoryArtifactStore()
    first_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )

    view = await first_process.start_run(
        baseline=baseline(document_id),
        instruction="Change 45 days to 30 days and nothing else.",
    )
    assert view.state is SyncRunState.EDITING
    assert view.attention_code == "SUPERDOCS_JOB_START_OUTCOME_UNKNOWN"

    restarted_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    recovered = await restarted_process.resume(view.run_id)

    assert recovered.provider_job_id == provider.job_id
    assert provider.start_calls == 1
    async with sessions() as session:
        effect = await session.scalar(
            select(ExternalEffect).where(
                ExternalEffect.sync_run_id == view.run_id,
                ExternalEffect.effect_type == EffectType.SUPERDOCS_JOB_START,
            )
        )
        jobs = await session.scalar(
            select(func.count())
            .select_from(SuperDocsJob)
            .where(SuperDocsJob.sync_run_id == view.run_id)
        )
    assert effect is not None and effect.outcome is EffectOutcome.SUCCEEDED
    assert jobs == 1


async def test_lost_upload_response_recovers_fresh_session_without_second_upload(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.upload_loses_response = True
    artifacts = InMemoryArtifactStore()
    first_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    first = await first_process.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    assert first.attention_code == "SUPERDOCS_UPLOAD_OUTCOME_UNKNOWN"

    restarted_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    recovered = await restarted_process.resume(first.run_id)

    assert recovered.session_document_id == "doc_primary"
    assert recovered.durable_document_id == "durable-document-1"
    assert recovered.provider_job_id == provider.job_id
    assert provider.upload_calls == 1
    assert provider.start_calls == 1


@pytest.mark.parametrize("stage", ["upload", "job_start"])
async def test_unknown_superdocs_effect_is_not_retried_when_recovery_state_is_absent(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
    stage: str,
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    if stage == "upload":
        provider.upload_loses_response = True
        provider.hide_upload_from_roster = True
    else:
        provider.start_loses_response = True
        provider.hide_job_from_roster = True
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )

    first = await service.start_run(
        baseline=baseline(document_id), instruction=f"Bounded {stage} recovery test."
    )
    first_call_count = provider.upload_calls if stage == "upload" else provider.start_calls
    assert first_call_count == 1

    await service.resume(first.run_id)
    await service.resume(first.run_id)

    assert (provider.upload_calls if stage == "upload" else provider.start_calls) == 1
    assert first.attention_code == f"SUPERDOCS_{stage.upper()}_OUTCOME_UNKNOWN"
    async with sessions() as session:
        effect = await session.scalar(
            select(ExternalEffect).where(
                ExternalEffect.sync_run_id == first.run_id,
                ExternalEffect.effect_type
                == (
                    EffectType.SUPERDOCS_UPLOAD
                    if stage == "upload"
                    else EffectType.SUPERDOCS_JOB_START
                ),
            )
        )
    assert effect is not None
    assert effect.outcome is EffectOutcome.UNKNOWN
    assert effect.reconciliation_evidence["absence_treated_as_definitive_non_occurrence"] is False


async def test_definitive_upload_rejection_is_not_retried_without_explicit_override(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.upload_rejects = True
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    assert started.attention_code == "SUPERDOCS_UPLOAD_REJECTED"
    assert provider.upload_calls == 1

    still_blocked = await service.resume(started.run_id)
    assert still_blocked.attention_code == "SUPERDOCS_UPLOAD_REJECTED"
    assert provider.upload_calls == 1
    assert started.run_id not in await service.list_resumable_run_ids()

    recovered = await service.resume(started.run_id, allow_definitive_retry=True)
    assert recovered.provider_job_id == provider.job_id
    assert provider.upload_calls == 2


async def test_review_requires_complete_explicit_set_and_preserves_replacement_lineage(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    artifacts = InMemoryArtifactStore()
    service = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    started = await service.start_run(
        baseline=baseline(document_id),
        instruction="Update two clauses and nothing else.",
    )
    provider.job = provider.review_job(
        proposal("change-a", "chunk-a", "<p>A</p>", "<p>A approved</p>", "A"),
        proposal("change-b", "chunk-b", "<p>B</p>", "<p>B rejected</p>", "B"),
    )
    awaiting = await service.resume(started.run_id)
    assert awaiting.state is SyncRunState.AWAITING_REVIEW
    assert len(awaiting.pending_proposals) == 2

    with pytest.raises(IncompleteDecisionSet):
        await service.submit_decisions(
            started.run_id,
            decisions=(
                DecisionInput(proposal_id=awaiting.pending_proposals[0].proposal_id, approve=True),
            ),
            reviewer_subject="reviewer-1",
        )
    assert provider.decision_calls == []

    by_change = {item.change_id: item for item in awaiting.pending_proposals}
    restarted_at_review = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    submitted_decisions = (
        DecisionInput(proposal_id=by_change["change-a"].proposal_id, approve=True),
        DecisionInput(
            proposal_id=by_change["change-b"].proposal_id,
            approve=False,
            feedback="Keep B and add a narrower clarification.",
        ),
    )
    await restarted_at_review.submit_decisions(
        started.run_id,
        decisions=submitted_decisions,
        reviewer_subject="reviewer-1",
    )
    assert [item.approved for item in provider.decision_calls[0]] == [True, False]
    replayed = await restarted_at_review.submit_decisions(
        started.run_id,
        decisions=submitted_decisions,
        reviewer_subject="reviewer-1",
    )
    assert replayed.state is SyncRunState.EDITING
    assert len(provider.decision_calls) == 1
    with pytest.raises(ReviewOperationInvalid, match="immutable persisted set"):
        await restarted_at_review.submit_decisions(
            started.run_id,
            decisions=(
                DecisionInput(
                    proposal_id=by_change["change-a"].proposal_id,
                    approve=False,
                ),
                submitted_decisions[1],
            ),
            reviewer_subject="reviewer-1",
        )

    provider.job = provider.review_job(
        proposal(
            "replacement-1",
            "chunk-b",
            "<p>B</p>",
            "<p>B. Narrow clarification.</p>",
            "Replacement after feedback",
        )
    )
    round_two = await service.resume(started.run_id)
    replacement = round_two.pending_proposals[0]
    assert replacement.change_id == "replacement-1"

    async with sessions() as session:
        stored = await session.get(ProposedChange, replacement.proposal_id)
        replaced = (
            await session.get(ProposedChange, stored.replaces_proposal_id) if stored else None
        )
        rounds = (
            await session.scalars(
                select(ReviewRound)
                .where(ReviewRound.sync_run_id == started.run_id)
                .order_by(ReviewRound.ordinal)
            )
        ).all()
        decisions = (
            await session.scalars(
                select(ReviewDecision).where(ReviewDecision.sync_run_id == started.run_id)
            )
        ).all()
    assert stored is not None and replaced is not None
    assert replaced.superdocs_change_id == "change-b"
    assert [item.ordinal for item in rounds] == [1, 2]
    assert sorted(item.decision for item in decisions) == [
        ChangeDecision.APPROVE,
        ChangeDecision.REJECT,
    ]


async def test_lost_review_response_reconciles_same_job_without_resubmission(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    artifacts = InMemoryArtifactStore()
    first_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    started = await first_process.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    provider.job = provider.review_job(
        proposal("change-a", "chunk-a", "<p>45 days</p>", "<p>30 days</p>", "Bounded")
    )
    awaiting = await first_process.resume(started.run_id)
    provider.decision_loses_response = True
    submitted = await first_process.submit_decisions(
        started.run_id,
        decisions=(
            DecisionInput(proposal_id=awaiting.pending_proposals[0].proposal_id, approve=True),
        ),
        reviewer_subject="reviewer-1",
    )
    assert submitted.attention_code == "SUPERDOCS_REVIEW_SUBMISSION_OUTCOME_UNKNOWN"
    assert started.run_id in await first_process.list_resumable_run_ids()

    restarted_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    reconciled = await restarted_process.resume(started.run_id)

    assert reconciled.state is SyncRunState.EDITING
    assert reconciled.attention_code is None
    assert provider.start_calls == 1
    assert len(provider.decision_calls) == 1
    async with sessions() as session:
        effect = await session.scalar(
            select(ExternalEffect).where(
                ExternalEffect.sync_run_id == started.run_id,
                ExternalEffect.effect_type == EffectType.SUPERDOCS_REVIEW_SUBMISSION,
            )
        )
    assert effect is not None and effect.outcome is EffectOutcome.SUCCEEDED


async def test_same_intent_reuses_run_but_new_revision_gets_fresh_ingestion(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    first = await service.start_run(
        baseline=baseline(document_id, "revision-A"),
        instruction="Change 45 days to 30 days only.",
    )
    duplicate = await service.start_run(
        baseline=baseline(document_id, "revision-A"),
        instruction="Change 45 days to 30 days only.",
    )
    second_revision = await service.start_run(
        baseline=baseline(document_id, "revision-B"),
        instruction="Change 45 days to 30 days only.",
    )

    assert duplicate.run_id == first.run_id
    assert second_revision.run_id != first.run_id
    assert second_revision.session_id != first.session_id
    assert provider.upload_calls == 2
    assert provider.start_calls == 2


async def test_continue_prompt_is_exact_and_malformed_review_fails_closed(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Make one bounded edit."
    )
    provider.job = provider.review_job(awaiting_kind="continue_prompt")
    awaiting = await service.resume(started.run_id)
    assert awaiting.awaiting_kind == "CONTINUE_PROMPT"
    await service.submit_continue(
        started.run_id, should_continue=True, reviewer_subject="reviewer-1"
    )
    assert provider.continue_calls == [True]

    provider.job = provider.review_job(awaiting_kind=None)
    with pytest.raises(ReviewPayloadInvalid):
        await service.resume(started.run_id)
    status = await service.get_run(started.run_id)
    assert status.state is SyncRunState.AWAITING_REVIEW
    assert status.attention_code == "SUPERDOCS_REVIEW_PAYLOAD_INVALID"


async def test_lost_stop_response_reconciles_explicit_continue_prompt_decision(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.continue_loses_response = True
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Make one bounded edit."
    )
    provider.job = provider.review_job(awaiting_kind="continue_prompt")
    await service.resume(started.run_id)

    unknown = await service.submit_continue(
        started.run_id, should_continue=False, reviewer_subject="reviewer-1"
    )
    assert unknown.attention_code == "SUPERDOCS_CONTINUE_OUTCOME_UNKNOWN"

    restarted = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    reconciled = await restarted.resume(started.run_id)
    assert reconciled.state is SyncRunState.EDITING
    assert provider.continue_calls == [False]
    async with sessions() as session:
        round_row = await session.scalar(
            select(ReviewRound).where(ReviewRound.sync_run_id == started.run_id)
        )
    assert round_row is not None
    assert round_row.resolution is ReviewRoundResolution.STOP
    assert round_row.resolved_by_subject == "reviewer-1"


async def test_conflicting_continue_choice_cannot_replace_unknown_persisted_choice(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.continue_loses_response = True
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Make one bounded edit."
    )
    provider.job = provider.review_job(awaiting_kind="continue_prompt")
    await service.resume(started.run_id)
    await service.submit_continue(
        started.run_id, should_continue=False, reviewer_subject="reviewer-1"
    )

    with pytest.raises(ReviewOperationInvalid, match="immutable persisted choice"):
        await service.submit_continue(
            started.run_id, should_continue=True, reviewer_subject="reviewer-2"
        )

    assert provider.continue_calls == [False]


async def test_stale_concurrent_poll_cannot_regress_completed_job(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    artifacts = InMemoryArtifactStore()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=artifacts,
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    provider.block_job_read = asyncio.Event()
    stale_poll = asyncio.create_task(service.resume(started.run_id))
    await provider.job_read_entered.wait()

    completed_snapshot = provider.completed_job()
    await service._update_job(started.run_id, completed_snapshot)
    provider.job = completed_snapshot
    provider.block_job_read.set()
    recovered = await stale_poll

    assert recovered.state is SyncRunState.REVIEWED_EXPORT_READY
    async with sessions() as session:
        job = await session.scalar(
            select(SuperDocsJob).where(SuperDocsJob.sync_run_id == started.run_id)
        )
    assert job is not None and job.status is SuperDocsJobStatus.COMPLETED


async def test_completed_job_recovery_refocuses_and_exports_without_second_edit_job(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    provider.export_times_out_once = True
    artifacts = InMemoryArtifactStore()
    first_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    started = await first_process.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    provider.job = provider.completed_job()
    with pytest.raises(SuperDocsRequestError):
        await first_process.resume(started.run_id)

    async with sessions() as session:
        job = await session.scalar(
            select(SuperDocsJob).where(SuperDocsJob.sync_run_id == started.run_id)
        )
        export_before = await session.scalar(
            select(SuperDocsExport).where(SuperDocsExport.sync_run_id == started.run_id)
        )
    assert job is not None and job.status is SuperDocsJobStatus.COMPLETED
    assert export_before is None

    restarted_process = SuperDocsWorkflow(
        sessions=sessions, superdocs=provider, artifacts=artifacts, owner_subject="owner-1"
    )
    completed = await restarted_process.resume(started.run_id)

    assert completed.state is SyncRunState.REVIEWED_EXPORT_READY
    assert completed.export is not None
    assert completed.export.sha256 == _sha(b"PK\x03\x04reviewed document contains 30 days")
    assert provider.start_calls == 1
    assert provider.focus_calls == ["doc_primary", "doc_primary"]
    assert provider.export_calls == 2
    assert await artifacts.read(completed.export.artifact_reference) == (
        b"PK\x03\x04reviewed document contains 30 days"
    )
    machine_export = await restarted_process.get_export_artifact(started.run_id)
    assert machine_export.metadata == completed.export
    assert machine_export.content == b"PK\x03\x04reviewed document contains 30 days"


async def test_provider_completion_cannot_bypass_an_explicit_proposal_decision(
    workflow_database: tuple[AsyncEngine, async_sessionmaker[AsyncSession], UUID],
) -> None:
    _, sessions, document_id = workflow_database
    provider = FakeSuperDocs()
    service = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=provider,
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-1",
    )
    started = await service.start_run(
        baseline=baseline(document_id), instruction="Change 45 days to 30 days only."
    )
    provider.job = provider.review_job(
        proposal("change-a", "chunk-a", "<p>45 days</p>", "<p>30 days</p>", "Bounded")
    )
    await service.resume(started.run_id)
    provider.job = provider.completed_job()

    with pytest.raises(RecoveryBlocked, match="unresolved explicit review lineage"):
        await service.resume(started.run_id)
    blocked = await service.get_run(started.run_id)
    assert blocked.state is SyncRunState.AWAITING_REVIEW
    assert blocked.attention_code == "SUPERDOCS_COMPLETED_WITH_UNRESOLVED_REVIEW"
    assert blocked.export is None
    assert provider.focus_calls == []
    assert provider.export_calls == 0
