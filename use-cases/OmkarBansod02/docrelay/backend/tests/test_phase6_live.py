"""One opt-in production Phase 6 proof against synthetic Google Docs only."""

import hashlib
import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from docrelay.core.config import Settings
from docrelay.domain.enums import (
    BackupStatus,
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
from docrelay.domain.write_plan import GoogleDocsBatchUpdate
from docrelay.integrations.google.contracts import (
    CommitClassification,
    GoogleWriteBackPort,
)
from docrelay.integrations.google.read_only import DRIVE_API_BASE
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.integrations.google.write_back import DRIVE_FOLDER_MIME
from docrelay.persistence.database import Database
from docrelay.persistence.models import (
    Backup,
    CloudConnection,
    ExternalEffect,
    ProposedChange,
    ReviewDecision,
    ReviewRound,
    SourceSnapshot,
    SuperDocsDocument,
    SuperDocsExport,
    SuperDocsJob,
    SuperDocsSession,
    SyncRun,
    VerificationResult,
    WriteConflict,
    WritePlan,
)
from docrelay.services.write_planning import DryRunStatus, WritePlanningService
from docrelay.services.writeback import (
    WriteBackService,
    WriteBackStatus,
    _text_at_operation_range,
)

pytestmark = pytest.mark.live_google
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
OLD_HTML = "<p>Payment is due within 45 days.</p>"
NEW_HTML = "<p>Payment is due within 30 days.</p>"


async def test_one_real_success_and_one_real_conflict() -> None:
    if os.environ.get("DOCRELAY_RUN_LIVE_PHASE6") != "1":
        pytest.skip("set DOCRELAY_RUN_LIVE_PHASE6=1 for the bounded Phase 6 proof")
    success_file_id = os.environ.get("DOCRELAY_LIVE_PHASE6_SUCCESS_FILE_ID")
    conflict_file_id = os.environ.get("DOCRELAY_LIVE_PHASE6_CONFLICT_FILE_ID")
    existing_success_run = os.environ.get("DOCRELAY_LIVE_PHASE6_SUCCESS_RUN_ID")
    create_fixtures = os.environ.get("DOCRELAY_LIVE_PHASE6_CREATE_FIXTURES") == "1"
    if not create_fixtures and (not success_file_id or not conflict_file_id):
        pytest.skip("Phase 6 live proof requires two synthetic native Google Doc IDs")

    settings = Settings()
    runtime = GoogleRuntime.from_settings(settings)
    assert runtime is not None and runtime.write_client_factory is not None
    database = Database(settings.database_url)

    async def provider_factory(session: AsyncSession, connection_id: UUID) -> GoogleWriteBackPort:
        return await _google_service(session, runtime, settings).write_client(connection_id)

    execution = WriteBackService(
        sessions=database.sessions,
        owner_subject=settings.docrelay_owner_subject,
        provider_factory=provider_factory,
    )
    try:
        async with database.sessions() as session:
            connection = await session.scalar(
                select(CloudConnection).where(
                    CloudConnection.owner_subject == settings.docrelay_owner_subject,
                    CloudConnection.provider == Provider.GOOGLE,
                    CloudConnection.status == ConnectionStatus.CONNECTED,
                )
            )
            assert connection is not None
            connection_id = connection.id
            if create_fixtures:
                success_file_id, conflict_file_id = await _create_google_fixtures(
                    session,
                    runtime,
                    settings,
                    connection,
                )

        assert success_file_id is not None and conflict_file_id is not None
        assert success_file_id != conflict_file_id

        success_run = (
            UUID(existing_success_run)
            if existing_success_run
            else await _prepare_live_plan(
                database,
                runtime,
                settings,
                connection_id,
                success_file_id,
                role="success",
            )
        )
        success = await execution.execute(success_run)
        repeated = await execution.execute(success_run)
        assert success.status is repeated.status is WriteBackStatus.WRITE_VERIFIED
        assert success.backup_verified and success.structurally_verified
        assert success.resulting_revision_id != success.baseline_revision_id

        async with database.sessions() as session:
            success_plan = await session.scalar(
                select(WritePlan).where(WritePlan.sync_run_id == success_run)
            )
            success_backup = await session.scalar(
                select(Backup).where(Backup.sync_run_id == success_run)
            )
            verification = await session.scalar(
                select(VerificationResult).where(VerificationResult.sync_run_id == success_run)
            )
            effects = tuple(
                await session.scalars(
                    select(ExternalEffect).where(ExternalEffect.sync_run_id == success_run)
                )
            )
            assert success_plan is not None
            assert success_backup is not None
            assert success_backup.status is BackupStatus.VERIFIED
            assert success_backup.provider_backup_file_id is not None
            assert verification is not None
            assert verification.report["complete_structure_matches"] is True
            assert verification.report["unaffected_structure_matches"] is True
            assert {
                effect.effect_type: (effect.attempt_count, effect.outcome) for effect in effects
            } == {
                EffectType.GOOGLE_BACKUP_COPY: (1, EffectOutcome.SUCCEEDED),
                EffectType.GOOGLE_BATCH_UPDATE: (1, EffectOutcome.SUCCEEDED),
            }
            source_snapshot = await session.scalar(
                select(SourceSnapshot).where(SourceSnapshot.sync_run_id == success_run)
            )
            assert source_snapshot is not None
            assert success_backup.canonical_sha256 == source_snapshot.native_canonical_sha256
            permission_evidence = (success_backup.acl_evidence or {}).get("permission_comparison")
            assert isinstance(permission_evidence, dict)
            assert permission_evidence["backup_not_broader"] is True
            backup_file_id = success_backup.provider_backup_file_id
            parent_id = success_plan.payload["source"]["parent_ids"][0]
            operation = GoogleDocsBatchUpdate.model_validate(
                success_plan.payload["provider_operations"][0]
            )

        async with database.sessions() as session:
            provider = await provider_factory(session, connection_id)
        target = await provider.inspect_current(
            file_id=success_file_id, destination_parent_id=parent_id
        )
        backup_snapshot = await provider.inspect_current(
            file_id=backup_file_id, destination_parent_id=parent_id
        )
        assert _text_at_operation_range(target.canonical_payload, operation) == "30"
        assert _text_at_operation_range(backup_snapshot.canonical_payload, operation) == "45"

        conflict_run = await _prepare_live_plan(
            database,
            runtime,
            settings,
            connection_id,
            conflict_file_id,
            role="conflict",
        )
        async with database.sessions() as session:
            conflict_plan = await session.scalar(
                select(WritePlan).where(WritePlan.sync_run_id == conflict_run)
            )
            assert conflict_plan is not None
            conflict_operation = GoogleDocsBatchUpdate.model_validate(
                conflict_plan.payload["provider_operations"][0]
            )
            conflict_parent = conflict_plan.payload["source"]["parent_ids"][0]
        human_requests = deepcopy(conflict_operation.requests)
        human_requests[1]["insertText"]["text"] = "99"  # type: ignore[index]
        human_operation = GoogleDocsBatchUpdate(
            required_revision_id=conflict_operation.required_revision_id,
            requests=human_requests,
        )
        human_result = await provider.commit_guarded(
            file_id=conflict_file_id,
            operation=human_operation,
        )
        assert human_result.classification is CommitClassification.SUCCEEDED
        human_state = await provider.inspect_current(
            file_id=conflict_file_id, destination_parent_id=conflict_parent
        )
        assert human_state.revision_id != conflict_operation.required_revision_id
        assert _text_at_operation_range(human_state.canonical_payload, human_operation) == "99"

        conflict = await execution.execute(conflict_run)
        after_conflict = await provider.inspect_current(
            file_id=conflict_file_id, destination_parent_id=conflict_parent
        )
        assert conflict.status is WriteBackStatus.CONFLICT
        assert conflict.conflict is not None
        assert conflict.conflict.detection_stage == "BEFORE_BACKUP"
        assert after_conflict.revision_id == human_state.revision_id
        assert after_conflict.canonical_sha256 == human_state.canonical_sha256
        assert _text_at_operation_range(after_conflict.canonical_payload, human_operation) == "99"

        async with database.sessions() as session:
            conflict_row = await session.scalar(
                select(WriteConflict).where(WriteConflict.sync_run_id == conflict_run)
            )
            conflict_effects = tuple(
                await session.scalars(
                    select(ExternalEffect).where(ExternalEffect.sync_run_id == conflict_run)
                )
            )
            assert conflict_row is not None
            assert (
                sum(
                    effect.attempt_count
                    for effect in conflict_effects
                    if effect.effect_type is EffectType.GOOGLE_BACKUP_COPY
                )
                == 0
            )
            assert not any(
                effect.effect_type is EffectType.GOOGLE_BATCH_UPDATE for effect in conflict_effects
            )
    finally:
        await runtime.close()
        await database.dispose()


async def _prepare_live_plan(
    database: Database,
    runtime: GoogleRuntime,
    settings: Settings,
    connection_id: UUID,
    file_id: str,
    *,
    role: str,
) -> UUID:
    now = datetime.now(UTC)
    async with database.sessions() as session:
        captured = await _google_service(session, runtime, settings).register_and_capture(
            connection_id=connection_id, file_id=file_id
        )
        result = captured.result
        assert result.metadata.mime_type == GOOGLE_DOC_MIME
        run = SyncRun(
            cloud_document_id=captured.document.id,
            rule_snapshot={
                "schema_version": "docrelay.phase6-live-fixture.v1",
                "instruction": "Change 45 days to 30 days and nothing else.",
                "instruction_sha256": _sha256("Change 45 days to 30 days and nothing else."),
            },
            mode=SyncMode.PREVIEW,
            state=SyncRunState.REVIEWED_EXPORT_READY,
            state_version=7,
            intent_key=_sha256(f"phase6-live:{role}:{uuid4()}"),
            baseline_revision_id=result.revision_id,
            started_at=now,
        )
        session.add(run)
        await session.flush()
        snapshot = SourceSnapshot(
            sync_run_id=run.id,
            cloud_document_id=captured.document.id,
            provider_revision_id=result.revision_id,
            source_format=GOOGLE_DOC_MIME,
            captured_at=result.captured_at,
            native_raw_sha256=result.native_raw_sha256,
            native_canonical_sha256=result.native_canonical_sha256,
            exported_artifact_sha256=result.exported_docx_sha256,
            artifact_reference=f"phase6-live/{run.id}/baseline.docx",
            schema_version=result.canonicalizer_version,
            capability_evidence=result.metadata.capabilities.model_dump(mode="json"),
            provider_evidence={"selected_baseline_capture_id": str(captured.capture.id)},
        )
        session.add(snapshot)
        await session.flush()
        superdocs_session = SuperDocsSession(
            sync_run_id=run.id,
            session_id=f"phase6-live-fixture-{uuid4()}",
            raw_evidence={"fixture_only": True, "no_new_superdocs_call": True},
        )
        session.add(superdocs_session)
        await session.flush()
        document = SuperDocsDocument(
            superdocs_session_id=superdocs_session.id,
            source_snapshot_id=snapshot.id,
            role=SuperDocsDocumentRole.TARGET,
            session_document_id="document_primary",
            durable_document_id=f"phase6-live-document-{uuid4()}",
            upload_version_id=f"phase6-live-upload-{uuid4()}",
            final_version_id=f"phase6-live-final-{uuid4()}",
            baseline_html_sha256=_sha256(OLD_HTML),
            baseline_evidence={"fixture_only": True},
        )
        session.add(document)
        await session.flush()
        job = SuperDocsJob(
            sync_run_id=run.id,
            superdocs_session_id=superdocs_session.id,
            target_document_id=document.id,
            provider_job_id=f"phase6-live-job-{uuid4()}",
            status=SuperDocsJobStatus.COMPLETED,
            start_request_sha256=_sha256(f"phase6-live-job:{run.id}"),
            raw_state={"status": "completed", "fixture_only": True},
            usage_evidence={"new_superdocs_operations": 0},
            started_at=now,
            completed_at=now,
        )
        session.add(job)
        await session.flush()
        review_round = ReviewRound(
            sync_run_id=run.id,
            superdocs_job_id=job.id,
            ordinal=1,
            awaiting_kind=ReviewAwaitingKind.CHANGE_BATCH,
            raw_pending_evidence={"fixture_only": True},
            resolution=ReviewRoundResolution.SUBMIT_CHANGES,
            resolved_by_subject=settings.docrelay_owner_subject,
            resolved_at=now,
        )
        session.add(review_round)
        await session.flush()
        proposal = ProposedChange(
            sync_run_id=run.id,
            superdocs_job_id=job.id,
            review_round_id=review_round.id,
            target_document_id=document.id,
            superdocs_change_id=f"phase6-live-change-{uuid4()}",
            ordinal=1,
            operation=ProposalOperation.EDIT,
            chunk_id=f"phase6-live-chunk-{uuid4()}",
            old_html=OLD_HTML,
            new_html=NEW_HTML,
            payload_sha256=_sha256(f"{OLD_HTML}\n{NEW_HTML}"),
            raw_payload={"fixture_only": True, "operation": "edit"},
        )
        session.add(proposal)
        await session.flush()
        session.add(
            ReviewDecision(
                sync_run_id=run.id,
                proposed_change_id=proposal.id,
                decision=ChangeDecision.APPROVE,
                reviewer_subject=settings.docrelay_owner_subject,
                decision_sha256=_sha256(f"approve:{proposal.id}"),
            )
        )
        session.add(
            SuperDocsExport(
                sync_run_id=run.id,
                source_snapshot_id=snapshot.id,
                superdocs_session_id=superdocs_session.id,
                superdocs_document_id=document.id,
                superdocs_job_id=job.id,
                artifact_reference=f"phase6-live/{run.id}/approved.docx",
                sha256=result.exported_docx_sha256,
                size_bytes=result.exported_docx_size_bytes,
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                warnings=[],
                final_version_id=document.final_version_id,
                exported_at=now,
            )
        )
        await session.commit()
        run_id = run.id
        proposal_id = proposal.id

    dry_run = await WritePlanningService(
        sessions=database.sessions,
        owner_subject=settings.docrelay_owner_subject,
    ).dry_run(run_id, proposal_id=proposal_id)
    assert dry_run.status is DryRunStatus.READY
    assert dry_run.operation_types == ("deleteContentRange", "insertText")
    assert dry_run.provider_operation is not None
    assert dry_run.provider_operation["writeControl"] == {
        "requiredRevisionId": dry_run.source.baseline_revision_id
    }
    return run_id


def _google_service(
    session: AsyncSession, runtime: GoogleRuntime, settings: Settings
) -> GoogleConnectionService:
    return GoogleConnectionService(
        session=session,
        runtime=runtime,
        owner_subject=settings.docrelay_owner_subject,
        state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
        refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
        baseline_max_attempts=settings.google_baseline_max_attempts,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _create_google_fixtures(
    session: AsyncSession,
    runtime: GoogleRuntime,
    settings: Settings,
    connection: CloudConnection,
) -> tuple[str, str]:
    token = await _google_service(session, runtime, settings)._valid_access_token(connection)
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
    timeout = httpx.Timeout(settings.google_http_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as http:
        folder = await http.post(
            f"{DRIVE_API_BASE}/files",
            params={"fields": "id", "supportsAllDrives": "true"},
            json={
                "name": f"DocRelay Phase 6 live proof {datetime.now(UTC).isoformat()}",
                "mimeType": DRIVE_FOLDER_MIME,
            },
            headers=headers,
        )
        if not folder.is_success:
            raise AssertionError(f"synthetic folder creation failed: HTTP {folder.status_code}")
        folder_id = str(folder.json().get("id") or "")
        assert folder_id
        file_ids: list[str] = []
        for role in ("success", "conflict"):
            response = await http.post(
                f"{DRIVE_API_BASE}/files",
                params={"fields": "id", "supportsAllDrives": "true"},
                json={
                    "name": f"DocRelay Phase 6 synthetic {role}",
                    "mimeType": GOOGLE_DOC_MIME,
                    "parents": [folder_id],
                },
                headers=headers,
            )
            if not response.is_success:
                raise AssertionError(
                    f"synthetic document creation failed: HTTP {response.status_code}"
                )
            file_id = str(response.json().get("id") or "")
            assert file_id
            file_ids.append(file_id)

    reader = runtime.read_client_factory(token)
    writer_factory = runtime.write_client_factory
    assert writer_factory is not None
    writer = writer_factory(token)
    for file_id in file_ids:
        empty = await reader.get_document(file_id)
        initialized = await writer.commit_guarded(
            file_id=file_id,
            operation=GoogleDocsBatchUpdate(
                required_revision_id=empty.revision_id,
                requests=(
                    {
                        "insertText": {
                            "location": {"tabId": "t.0", "index": 1},
                            "text": "Payment is due within 45 days.",
                        }
                    },
                ),
            ),
        )
        assert initialized.classification is CommitClassification.SUCCEEDED
    return file_ids[0], file_ids[1]
