import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from docrelay.domain.enums import (
    ChangeDecision,
    ConnectionStatus,
    ProposalOperation,
    Provider,
    ReviewAwaitingKind,
    ReviewRoundResolution,
    SuperDocsDocumentRole,
    SuperDocsJobStatus,
    SyncMode,
    SyncRunState,
)
from docrelay.integrations.google.canonical import sha256_json
from docrelay.persistence.base import Base
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    ExternalEffect,
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
)
from docrelay.services.artifacts import InMemoryArtifactStore
from docrelay.services.write_planning import DryRunStatus, DryRunView, WritePlanningService

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class CorruptingReadArtifactStore(InMemoryArtifactStore):
    async def read(self, reference: str) -> bytes:
        await super().read(reference)
        return b"tampered reviewed export"


def _canonical() -> dict[str, object]:
    return {
        "schema": "docrelay.google-native-canonical.v1",
        "tabs": [
            {
                "tabProperties": {
                    "tabId": "t.0",
                    "title": "Tab 1",
                    "index": 0,
                    "nestingLevel": 0,
                    "parentTabId": None,
                },
                "body": [
                    {
                        "startIndex": 162,
                        "endIndex": 193,
                        "type": "paragraph",
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": None,
                        "positionedObjectIds": [],
                        "runs": [
                            {
                                "kind": "text",
                                "startIndex": 162,
                                "endIndex": 193,
                                "text": "Payment is due within 45 days.\n",
                                "style": {},
                            }
                        ],
                    }
                ],
                "headers": {},
                "footers": {},
                "footnotes": {},
                "documentStyle": {},
                "namedStyles": {},
                "lists": {},
                "namedRanges": {},
                "inlineObjects": {},
                "positionedObjects": {},
                "childTabs": [],
            }
        ],
    }


async def test_dry_run_persists_one_deterministic_proof_and_plan_without_google_effects() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    canonical = _canonical()
    canonical_hash = sha256_json(canonical)
    export_content = b"PK\x03\x04reviewed export identity"
    export_sha256 = hashlib.sha256(export_content).hexdigest()
    artifacts = InMemoryArtifactStore()
    await artifacts.put("exports/run-a.docx", export_content, export_sha256)

    async with sessions() as session:
        connection = CloudConnection(
            owner_subject="owner-a",
            provider=Provider.GOOGLE,
            provider_account_subject="principal-a",
            status=ConnectionStatus.CONNECTED,
            granted_scopes={"scopes": ["drive.file"]},
        )
        session.add(connection)
        await session.flush()
        document = CloudDocument(
            connection_id=connection.id,
            provider_file_id="google-file-a",
            mime_type="application/vnd.google-apps.document",
            parent_ids=["parent-a"],
            last_seen_revision_id="revision-A",
        )
        session.add(document)
        await session.flush()
        capture = GoogleBaselineCapture(
            cloud_document_id=document.id,
            provider_revision_id="revision-A",
            native_raw_sha256="1" * 64,
            native_canonical_sha256=canonical_hash,
            exported_docx_sha256="2" * 64,
            exported_docx_size_bytes=9000,
            canonicalizer_version="docrelay.google-native-canonical.v1",
            canonical_payload=canonical,
            capability_evidence={"canModifyContent": True},
            parent_ids=["parent-a"],
            attempt_count=1,
            capture_started_at=NOW,
            captured_at=NOW,
            provider_evidence={"read_only": True},
        )
        session.add(capture)
        await session.flush()
        run = SyncRun(
            cloud_document_id=document.id,
            folder_rule_id=None,
            folder_rule_version=None,
            rule_snapshot={
                "instruction": "Change 45 days to 30 days.",
                "instruction_sha256": "3" * 64,
            },
            mode=SyncMode.PREVIEW,
            state=SyncRunState.REVIEWED_EXPORT_READY,
            state_version=7,
            intent_key="4" * 64,
            baseline_revision_id="revision-A",
            started_at=NOW,
        )
        session.add(run)
        await session.flush()
        snapshot = SourceSnapshot(
            sync_run_id=run.id,
            cloud_document_id=document.id,
            provider_revision_id="revision-A",
            source_format="application/vnd.google-apps.document",
            captured_at=NOW,
            native_raw_sha256="1" * 64,
            native_canonical_sha256=canonical_hash,
            exported_artifact_sha256="5" * 64,
            artifact_reference="baselines/run-a.docx",
            schema_version="docrelay.google-native-canonical.v1",
            capability_evidence={"canModifyContent": True},
            provider_evidence={"selected_baseline_capture_id": str(capture.id)},
        )
        session.add(snapshot)
        await session.flush()
        superdocs_session = SuperDocsSession(
            sync_run_id=run.id,
            session_id="session-a",
            raw_evidence={"fresh_ingestion": True},
        )
        session.add(superdocs_session)
        await session.flush()
        superdocs_document = SuperDocsDocument(
            superdocs_session_id=superdocs_session.id,
            source_snapshot_id=snapshot.id,
            role=SuperDocsDocumentRole.TARGET,
            session_document_id="document-a",
            durable_document_id="durable-a",
            upload_version_id="upload-a",
            final_version_id="final-a",
            baseline_html_sha256="6" * 64,
            baseline_evidence={"fresh": True},
        )
        session.add(superdocs_document)
        await session.flush()
        job = SuperDocsJob(
            sync_run_id=run.id,
            superdocs_session_id=superdocs_session.id,
            target_document_id=superdocs_document.id,
            provider_job_id="job-a",
            status=SuperDocsJobStatus.COMPLETED,
            start_request_sha256="7" * 64,
            raw_state={"status": "completed"},
            usage_evidence={"ops_charged": 1},
            started_at=NOW,
            completed_at=NOW,
        )
        session.add(job)
        await session.flush()
        review_round = ReviewRound(
            sync_run_id=run.id,
            superdocs_job_id=job.id,
            ordinal=1,
            awaiting_kind=ReviewAwaitingKind.CHANGE_BATCH,
            raw_pending_evidence={"change_ids": ["change-a"]},
            resolution=ReviewRoundResolution.SUBMIT_CHANGES,
            resolved_by_subject="owner-a",
            resolved_at=NOW,
        )
        session.add(review_round)
        await session.flush()
        proposal = ProposedChange(
            sync_run_id=run.id,
            superdocs_job_id=job.id,
            review_round_id=review_round.id,
            target_document_id=superdocs_document.id,
            superdocs_change_id="change-a",
            ordinal=1,
            operation=ProposalOperation.EDIT,
            chunk_id="ephemeral-chunk-a",
            old_html="<p>Payment is due within 45 days.</p>",
            new_html="<p>Payment is due within 30 days.</p>",
            payload_sha256="8" * 64,
            raw_payload={"operation": "edit"},
        )
        session.add(proposal)
        await session.flush()
        session.add(
            ReviewDecision(
                sync_run_id=run.id,
                proposed_change_id=proposal.id,
                decision=ChangeDecision.APPROVE,
                reviewer_subject="owner-a",
                decision_sha256="9" * 64,
            )
        )
        session.add(
            SuperDocsExport(
                sync_run_id=run.id,
                source_snapshot_id=snapshot.id,
                superdocs_session_id=superdocs_session.id,
                superdocs_document_id=superdocs_document.id,
                superdocs_job_id=job.id,
                artifact_reference="exports/run-a.docx",
                sha256=export_sha256,
                size_bytes=len(export_content),
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                warnings=[],
                final_version_id="final-a",
                exported_at=NOW,
            )
        )
        await session.commit()
        run_id = run.id
        proposal_id = proposal.id

    service = WritePlanningService(
        sessions=sessions,
        owner_subject="owner-a",
        artifacts=artifacts,
    )
    first = await service.dry_run(run_id, proposal_id=proposal_id)
    second = await service.dry_run(run_id, proposal_id=proposal_id)

    assert first.status is DryRunStatus.READY
    assert first == second
    assert first.old_text == "45"
    assert first.new_text == "30"
    assert first.context is not None
    assert first.context.before.text == "Payment is due within 45 days."
    assert first.context.after.text == "Payment is due within 30 days."
    assert (
        first.context.before.text[
            first.context.before.highlight_start : first.context.before.highlight_end
        ]
        == first.old_text
    )
    assert (
        first.context.after.text[
            first.context.after.highlight_start : first.context.after.highlight_end
        ]
        == first.new_text
    )
    before_prefix = first.context.before.text[: first.context.before.highlight_start]
    before_suffix = first.context.before.text[first.context.before.highlight_end :]
    after_prefix = first.context.after.text[: first.context.after.highlight_start]
    after_suffix = first.context.after.text[first.context.after.highlight_end :]
    assert (before_prefix, before_suffix) == (after_prefix, after_suffix)
    assert first.context.source_snapshot_id == snapshot.id
    assert first.context.native_snapshot_sha256 == canonical_hash
    unsupported_with_context = first.model_dump(mode="python")
    unsupported_with_context["status"] = DryRunStatus.UNSUPPORTED
    with pytest.raises(ValidationError, match="non-ready dry-runs"):
        DryRunView.model_validate(unsupported_with_context)
    assert first.operation_types == ("deleteContentRange", "insertText")
    assert first.operation_count == 2
    assert first.cloud_mutation_performed is False
    assert first.provider_operation is not None
    assert first.provider_operation["writeControl"] == {"requiredRevisionId": "revision-A"}

    corrupt_artifacts = CorruptingReadArtifactStore()
    await corrupt_artifacts.put("exports/run-a.docx", export_content, export_sha256)
    corrupt = await WritePlanningService(
        sessions=sessions,
        owner_subject="owner-a",
        artifacts=corrupt_artifacts,
    ).dry_run(run_id, proposal_id=proposal_id)
    assert corrupt.status is DryRunStatus.STALE
    assert corrupt.context is None
    assert corrupt.reason is not None and "immutable identity" in corrupt.reason

    async with sessions() as session:
        proof_count = await session.scalar(select(func.count()).select_from(MappingProof))
        plan_count = await session.scalar(select(func.count()).select_from(WritePlan))
        effect_count = await session.scalar(select(func.count()).select_from(ExternalEffect))
    assert proof_count == 1
    assert plan_count == 1
    assert effect_count == 0
    await engine.dispose()
