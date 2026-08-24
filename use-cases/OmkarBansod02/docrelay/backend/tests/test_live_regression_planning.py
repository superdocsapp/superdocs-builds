import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

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
from docrelay.services.artifacts import InMemoryArtifactStore
from docrelay.services.write_planning import DryRunStatus, WritePlanningService

NOW = datetime(2026, 8, 13, 15, 0, tzinfo=UTC)


def _live_canonical_shape() -> dict[str, object]:
    """Sanitized shape from the 2026-08-13 failing Google capture."""
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
                        "startIndex": None,
                        "endIndex": 1,
                        "type": "sectionBreak",
                        "sectionStyle": {},
                    },
                    {
                        "startIndex": 1,
                        "endIndex": 32,
                        "type": "paragraph",
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": None,
                        "positionedObjectIds": [],
                        "runs": [
                            {
                                "kind": "text",
                                "startIndex": 1,
                                "endIndex": 32,
                                "text": "Payment is due within 45 days.\n",
                                "style": {},
                            }
                        ],
                    },
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


async def _seed_planning_run(
    decisions: Sequence[ChangeDecision],
) -> tuple[
    AsyncEngine,
    async_sessionmaker,
    InMemoryArtifactStore,
    UUID,
    tuple[UUID, ...],
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
    canonical = _live_canonical_shape()
    canonical_hash = sha256_json(canonical)
    export_content = b"PK\x03\x04reviewed export identity"
    export_sha256 = hashlib.sha256(export_content).hexdigest()
    artifacts = InMemoryArtifactStore()
    await artifacts.put("exports/live-regression.docx", export_content, export_sha256)

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
                "instruction": "Change the payment term.",
                "instruction_sha256": "3" * 64,
            },
            mode=SyncMode.PREVIEW,
            state=SyncRunState.REVIEWED_EXPORT_READY,
            state_version=7,
            intent_key=hashlib.sha256(
                ",".join(decision.value for decision in decisions).encode()
            ).hexdigest(),
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
            artifact_reference="baselines/live-regression.docx",
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
            raw_pending_evidence={"change_ids": [f"change-{i}" for i in range(len(decisions))]},
            resolution=ReviewRoundResolution.SUBMIT_CHANGES,
            resolved_by_subject="owner-a",
            resolved_at=NOW,
        )
        session.add(review_round)
        await session.flush()
        proposal_ids: list[UUID] = []
        for index, decision in enumerate(decisions, start=1):
            proposal = ProposedChange(
                sync_run_id=run.id,
                superdocs_job_id=job.id,
                review_round_id=review_round.id,
                target_document_id=superdocs_document.id,
                superdocs_change_id=f"change-{index}",
                ordinal=index,
                operation=ProposalOperation.EDIT,
                chunk_id=f"chunk-{index}",
                old_html="<p>Payment is due within 45 days.</p>",
                new_html=f"<p>Payment is due within {20 + index * 10} days.</p>",
                payload_sha256=f"{index + 7:x}" * 64,
                raw_payload={"operation": "edit"},
            )
            session.add(proposal)
            await session.flush()
            proposal_ids.append(proposal.id)
            session.add(
                ReviewDecision(
                    sync_run_id=run.id,
                    proposed_change_id=proposal.id,
                    decision=decision,
                    reviewer_subject="owner-a",
                    decision_sha256=f"{index + 9:x}" * 64,
                )
            )
        session.add(
            SuperDocsExport(
                sync_run_id=run.id,
                source_snapshot_id=snapshot.id,
                superdocs_session_id=superdocs_session.id,
                superdocs_document_id=superdocs_document.id,
                superdocs_job_id=job.id,
                artifact_reference="exports/live-regression.docx",
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

    return engine, sessions, artifacts, run_id, tuple(proposal_ids)


@pytest.mark.parametrize(
    ("decisions", "expected_status", "selected_index", "expected_code"),
    [
        ((ChangeDecision.APPROVE,), DryRunStatus.READY, 0, None),
        ((ChangeDecision.REJECT,), DryRunStatus.NOT_APPROVED, None, "NOT_APPROVED"),
        (
            (ChangeDecision.APPROVE, ChangeDecision.REJECT),
            DryRunStatus.READY,
            0,
            None,
        ),
        (
            (ChangeDecision.REJECT, ChangeDecision.APPROVE),
            DryRunStatus.READY,
            1,
            None,
        ),
        (
            (ChangeDecision.APPROVE, ChangeDecision.APPROVE),
            DryRunStatus.UNSUPPORTED,
            None,
            "OVERLAPPING_MAPPED_RANGES",
        ),
        (
            (ChangeDecision.REJECT, ChangeDecision.REJECT),
            DryRunStatus.NOT_APPROVED,
            None,
            "NOT_APPROVED",
        ),
    ],
)
async def test_review_roster_selects_exactly_one_approved_writable_proposal(
    decisions: tuple[ChangeDecision, ...],
    expected_status: DryRunStatus,
    selected_index: int | None,
    expected_code: str | None,
) -> None:
    engine, sessions, artifacts, run_id, proposal_ids = await _seed_planning_run(decisions)
    service = WritePlanningService(
        sessions=sessions,
        owner_subject="owner-a",
        artifacts=artifacts,
    )

    first = await service.dry_run(run_id)
    second = await service.dry_run(run_id)

    assert first.status is expected_status
    assert first.reason_code == expected_code
    assert first.cloud_mutation_performed is False
    assert first == second
    async with sessions() as session:
        proofs = tuple(await session.scalars(select(MappingProof)))
        plans = tuple(await session.scalars(select(WritePlan)))
        lineage = tuple(await session.scalars(select(WritePlanLineage)))
        decision_count = await session.scalar(select(func.count()).select_from(ReviewDecision))
    assert decision_count == len(decisions)
    if selected_index is None:
        assert first.proposal_id is None
        assert proofs == ()
        assert plans == ()
        assert lineage == ()
    else:
        selected_id = proposal_ids[selected_index]
        rejected_ids = {
            proposal_id
            for proposal_id, decision in zip(proposal_ids, decisions, strict=True)
            if decision is ChangeDecision.REJECT
        }
        assert first.proposal_id == selected_id
        assert len(proofs) == len(plans) == len(lineage) == 1
        assert proofs[0].proof_payload["lineage"]["proposal_id"] == str(selected_id)
        assert plans[0].payload["approval_lineage"][0]["proposal_id"] == str(selected_id)
        assert lineage[0].proposed_change_id == selected_id
        serialized_evidence = f"{proofs[0].proof_payload}{plans[0].payload}"
        assert all(str(rejected_id) not in serialized_evidence for rejected_id in rejected_ids)
    await engine.dispose()
