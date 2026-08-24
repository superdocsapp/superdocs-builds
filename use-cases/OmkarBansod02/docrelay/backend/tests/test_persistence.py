from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from docrelay.domain.enums import (
    ChangeDecision,
    ConnectionStatus,
    EffectOutcome,
    EffectType,
    ProposalOperation,
    Provider,
    ReviewAwaitingKind,
    ReviewRoundResolution,
    SuperDocsDocumentRole,
    SuperDocsJobStatus,
    SyncMode,
    SyncRunState,
)
from docrelay.domain.write_plan import SealedWritePlan
from docrelay.persistence.base import Base
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    ExternalEffect,
    FolderRule,
    MappingProof,
    ProposedChange,
    ReviewDecision,
    ReviewRound,
    SourceSnapshot,
    SuperDocsDocument,
    SuperDocsJob,
    SuperDocsSession,
    SyncRun,
    WatchConfig,
    WritePlan,
    WritePlanLineage,
)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
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
        yield session
    await engine.dispose()


async def test_essential_identity_and_review_lineage_persist(
    db_session: AsyncSession,
    write_plan_factory: Callable[..., SealedWritePlan],
) -> None:
    now = datetime(2026, 8, 7, 17, 0, tzinfo=UTC)
    connection = CloudConnection(
        owner_subject="owner-1",
        provider=Provider.GOOGLE,
        provider_account_subject="google-principal-1",
        status=ConnectionStatus.CONNECTED,
        granted_scopes={"scopes": ["drive.file"]},
    )
    db_session.add(connection)
    await db_session.flush()

    document = CloudDocument(
        connection_id=connection.id,
        provider_file_id="immutable-google-file-id",
        mime_type="application/vnd.google-apps.document",
        parent_ids=["parent-folder-id"],
        last_seen_revision_id="revision-A",
    )
    watch = WatchConfig(
        connection_id=connection.id,
        parent_folder_id="parent-folder-id",
        schedule="0 * * * *",
        timezone="UTC",
        default_mode=SyncMode.PREVIEW,
        enabled=False,
    )
    db_session.add_all([document, watch])
    await db_session.flush()

    rule = FolderRule(
        watch_config_id=watch.id,
        provider_folder_id="contracts-folder-id",
        version=1,
        instruction="Change only the explicitly approved payment token.",
        instruction_sha256="2" * 64,
        configuration={"model": "not-yet-selected"},
        supported_formats={"mime_types": ["application/vnd.google-apps.document"]},
        active=True,
    )
    db_session.add(rule)
    await db_session.flush()

    run = SyncRun(
        cloud_document_id=document.id,
        folder_rule_id=rule.id,
        folder_rule_version=rule.version,
        rule_snapshot={"instruction_sha256": rule.instruction_sha256},
        mode=SyncMode.PREVIEW,
        state=SyncRunState.AWAITING_REVIEW,
        state_version=4,
        intent_key="a" * 64,
        baseline_revision_id="revision-A",
        started_at=now,
    )
    db_session.add(run)
    await db_session.flush()

    snapshot = SourceSnapshot(
        sync_run_id=run.id,
        cloud_document_id=document.id,
        provider_revision_id="revision-A",
        source_format="application/vnd.google-apps.document",
        captured_at=now,
        native_raw_sha256="0" * 64,
        native_canonical_sha256="1" * 64,
        exported_artifact_sha256="2" * 64,
        schema_version="docrelay.google-canonical.v1",
        capability_evidence={"canModifyContent": True},
        provider_evidence={"revision_before": "revision-A", "revision_after": "revision-A"},
    )
    db_session.add(snapshot)
    await db_session.flush()

    superdocs_session = SuperDocsSession(
        sync_run_id=run.id,
        session_id="session-for-revision-A",
        raw_evidence={"fresh_ingestion": True},
    )
    db_session.add(superdocs_session)
    await db_session.flush()

    superdocs_document = SuperDocsDocument(
        superdocs_session_id=superdocs_session.id,
        source_snapshot_id=snapshot.id,
        role=SuperDocsDocumentRole.TARGET,
        session_document_id="doc_primary",
        durable_document_id="durable-audit-id",
        upload_version_id="upload-version-id",
        final_version_id="final-version-id",
        baseline_html_sha256="0" * 64,
        baseline_evidence={"chunks": 15},
    )
    db_session.add(superdocs_document)
    await db_session.flush()

    job = SuperDocsJob(
        sync_run_id=run.id,
        superdocs_session_id=superdocs_session.id,
        target_document_id=superdocs_document.id,
        provider_job_id="superdocs-job-id",
        status=SuperDocsJobStatus.AWAITING_APPROVAL,
        start_request_sha256="3" * 64,
        raw_state={"status": "awaiting_approval"},
        usage_evidence={"ops_charged": 1},
        started_at=now,
    )
    db_session.add(job)
    await db_session.flush()

    first_round = ReviewRound(
        sync_run_id=run.id,
        superdocs_job_id=job.id,
        ordinal=1,
        awaiting_kind=ReviewAwaitingKind.CHANGE_BATCH,
        raw_pending_evidence={"change_ids": ["rejected-change-id"]},
        resolution=ReviewRoundResolution.SUBMIT_CHANGES,
        resolved_by_subject="reviewer-1",
        resolved_at=now,
    )
    db_session.add(first_round)
    await db_session.flush()

    rejected_proposal = ProposedChange(
        sync_run_id=run.id,
        superdocs_job_id=job.id,
        review_round_id=first_round.id,
        target_document_id=superdocs_document.id,
        superdocs_change_id="rejected-change-id",
        operation=ProposalOperation.EDIT,
        chunk_id="fresh-ingestion-chunk-id",
        old_html="<p>twelve months</p>",
        new_html="<p>twenty-four months</p>",
        ai_explanation="Initial proposal",
        payload_sha256="4" * 64,
        raw_payload={"round": 1},
    )
    db_session.add(rejected_proposal)
    await db_session.flush()
    rejected_decision = ReviewDecision(
        sync_run_id=run.id,
        proposed_change_id=rejected_proposal.id,
        decision=ChangeDecision.REJECT,
        reviewer_subject="reviewer-1",
        feedback="Retain twelve months and add written renewal.",
        decision_sha256="5" * 64,
    )
    db_session.add(rejected_decision)

    second_round = ReviewRound(
        sync_run_id=run.id,
        superdocs_job_id=job.id,
        ordinal=2,
        awaiting_kind=ReviewAwaitingKind.CHANGE_BATCH,
        raw_pending_evidence={"change_ids": ["replacement-change-id"]},
        resolution=ReviewRoundResolution.SUBMIT_CHANGES,
        resolved_by_subject="reviewer-1",
        resolved_at=now,
    )
    db_session.add(second_round)
    await db_session.flush()
    approved_proposal = ProposedChange(
        sync_run_id=run.id,
        superdocs_job_id=job.id,
        review_round_id=second_round.id,
        target_document_id=superdocs_document.id,
        replaces_proposal_id=rejected_proposal.id,
        superdocs_change_id="replacement-change-id",
        operation=ProposalOperation.EDIT,
        chunk_id="fresh-ingestion-chunk-id",
        old_html="<p>twelve months</p>",
        new_html="<p>twelve months. Renewal requires written agreement.</p>",
        ai_explanation="Replacement after feedback",
        payload_sha256="6" * 64,
        raw_payload={"round": 2},
    )
    db_session.add(approved_proposal)
    await db_session.flush()
    approved_decision = ReviewDecision(
        sync_run_id=run.id,
        proposed_change_id=approved_proposal.id,
        decision=ChangeDecision.APPROVE,
        reviewer_subject="reviewer-1",
        decision_sha256="7" * 64,
    )
    db_session.add(approved_decision)
    await db_session.flush()

    mapping = MappingProof(
        sync_run_id=run.id,
        source_snapshot_id=snapshot.id,
        schema_version="docrelay.mapping-proof.v1",
        mapper_version="docrelay.google-plain-token-mapper.v1",
        integrity_sha256="3" * 64,
        proof_payload={"chunk_id": "fresh-ingestion-chunk-id", "unique": True},
    )
    db_session.add(mapping)
    await db_session.flush()

    sealed_plan = write_plan_factory(
        sync_run_id=run.id,
        snapshot_id=snapshot.id,
        rule_id=rule.id,
        mapping_proof_id=mapping.id,
        proposal_id=approved_proposal.id,
        decision_id=approved_decision.id,
    )
    plan = WritePlan(
        sync_run_id=run.id,
        source_snapshot_id=snapshot.id,
        mapping_proof_id=mapping.id,
        schema_version=sealed_plan.payload.schema_version,
        provider_file_id=sealed_plan.payload.source.provider_file_id,
        baseline_revision_id=sealed_plan.payload.source.baseline_revision_id,
        mapper_version=sealed_plan.payload.mapping.mapper_version,
        verifier_version=sealed_plan.payload.expected_postimage.verifier_version,
        provider_operations={
            "operations": [
                operation.model_dump(mode="json")
                for operation in sealed_plan.payload.provider_operations
            ]
        },
        expected_postimage_sha256=sealed_plan.payload.expected_postimage.canonical_sha256,
        payload=sealed_plan.payload.model_dump(mode="json"),
        integrity_sha256=sealed_plan.integrity_sha256,
        sealed_at=sealed_plan.payload.created_at,
        expires_at=sealed_plan.payload.expires_at,
    )
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        WritePlanLineage(
            write_plan_id=plan.id,
            proposed_change_id=approved_proposal.id,
            review_decision_id=approved_decision.id,
            ordinal=1,
        )
    )
    db_session.add(
        ExternalEffect(
            sync_run_id=run.id,
            effect_key="google-batch-update:plan-1",
            effect_type=EffectType.GOOGLE_BATCH_UPDATE,
            outcome=EffectOutcome.UNKNOWN,
            request_fingerprint="8" * 64,
            request_metadata={"write_plan_sha256": sealed_plan.integrity_sha256},
            attempt_count=1,
            started_at=now,
        )
    )
    await db_session.commit()

    stored_document = await db_session.scalar(
        select(CloudDocument).where(CloudDocument.provider_file_id == "immutable-google-file-id")
    )
    stored_superdocs = await db_session.scalar(
        select(SuperDocsDocument).where(
            SuperDocsDocument.superdocs_session_id == superdocs_session.id,
            SuperDocsDocument.session_document_id == "doc_primary",
        )
    )
    stored_replacement = await db_session.scalar(
        select(ProposedChange).where(ProposedChange.superdocs_change_id == "replacement-change-id")
    )
    stored_plan = await db_session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run.id))
    stored_effect = await db_session.scalar(
        select(ExternalEffect).where(ExternalEffect.sync_run_id == run.id)
    )

    assert stored_document is not None and stored_document.connection_id == connection.id
    assert stored_superdocs is not None
    assert stored_superdocs.session_document_id == "doc_primary"
    assert stored_superdocs.durable_document_id == "durable-audit-id"
    assert stored_replacement is not None
    assert stored_replacement.replaces_proposal_id == rejected_proposal.id
    assert stored_plan is not None
    assert stored_plan.baseline_revision_id == "revision-A"
    assert stored_plan.integrity_sha256 == sealed_plan.integrity_sha256
    assert stored_effect is not None and stored_effect.outcome is EffectOutcome.UNKNOWN
