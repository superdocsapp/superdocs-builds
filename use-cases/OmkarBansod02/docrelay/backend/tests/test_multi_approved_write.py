from collections.abc import Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
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
from docrelay.mapping.production import (
    BaselineSnapshot,
    MappingFailure,
    MappingFailureCode,
    ReviewedProposal,
    compile_write_plan,
    map_approved_replacements,
    map_replacement,
    normalize_reviewed_change,
    seal_mapped_set,
)
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
    VerificationResult,
    WritePlan,
    WritePlanLineage,
)
from docrelay.services.artifacts import InMemoryArtifactStore
from docrelay.services.superdocs_workflow import get_write_back_summary
from docrelay.services.write_planning import DryRunStatus, WritePlanningService
from docrelay.services.writeback import WriteBackService, WriteBackStatus
from tests.test_writeback_service import FakeGoogleWriteProvider

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64
TWO_HASH = "2" * 64
PAYMENT = "Payment terms are 30 days."
WARRANTY = "Warranty lasts 12 months."
SUPPORT = "Support hours are 9 to 5."
PAYMENT_14 = "Payment terms are 14 days."
WARRANTY_24 = "Warranty lasts 24 months."
SUPPORT_86 = "Support hours are 8 to 6."
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


def _paragraph(text: str, *, start: int) -> dict[str, object]:
    content = f"{text}\n"
    end = start + len(content.encode("utf-16-le")) // 2
    return {
        "startIndex": start,
        "endIndex": end,
        "type": "paragraph",
        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
        "bullet": None,
        "positionedObjectIds": [],
        "runs": [
            {
                "kind": "text",
                "startIndex": start,
                "endIndex": end,
                "text": content,
                "style": {},
            }
        ],
    }


def _canonical(paragraphs: Sequence[str], *, start: int = 1) -> dict[str, object]:
    body: list[dict[str, object]] = []
    index = start
    for text in paragraphs:
        paragraph = _paragraph(text, start=index)
        body.append(paragraph)
        index = int(paragraph["endIndex"])
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
                "body": body,
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


def _proposal(
    *,
    proposal_id: str,
    decision_id: str,
    old_paragraph: str,
    new_paragraph: str,
    superdocs_change_id: str = "change-a",
    chunk_id: str = "chunk-a",
    operation: ProposalOperation = ProposalOperation.EDIT,
    old_html: str | None = None,
    new_html: str | None = None,
) -> ReviewedProposal:
    return ReviewedProposal.model_validate(
        {
            "proposal_id": UUID(proposal_id),
            "decision_id": UUID(decision_id),
            "decision": ChangeDecision.APPROVE,
            "decision_sha256": ZERO_HASH,
            "superseded": False,
            "operation": operation,
            "review_round": 1,
            "session_id": "session-a",
            "session_document_id": "document-a",
            "durable_document_id": "durable-a",
            "job_id": "job-a",
            "superdocs_export_id": UUID("00000000-0000-0000-0000-000000000103"),
            "approved_export_sha256": ONE_HASH,
            "final_version_id": "final-a",
            "superdocs_change_id": superdocs_change_id,
            "chunk_id": chunk_id,
            "old_html": old_html if old_html is not None else f"<p>{old_paragraph}</p>",
            "new_html": new_html if new_html is not None else f"<p>{new_paragraph}</p>",
            "lineage_current": True,
        }
    )


def _baseline(payload: dict[str, object] | None = None, **changes: object) -> BaselineSnapshot:
    canonical = payload or _canonical((PAYMENT, WARRANTY, SUPPORT))
    values: dict[str, object] = {
        "snapshot_id": UUID("00000000-0000-0000-0000-000000000201"),
        "provider": Provider.GOOGLE,
        "provider_principal_subject": "principal-a",
        "provider_file_id": "google-file-a",
        "parent_ids": ("parent-a",),
        "baseline_revision_id": "revision-A",
        "run_baseline_revision_id": "revision-A",
        "capture_revision_id": "revision-A",
        "native_raw_sha256": ONE_HASH,
        "native_canonical_sha256": sha256_json(canonical),
        "exported_docx_sha256": TWO_HASH,
        "canonical_payload": canonical,
    }
    values.update(changes)
    return BaselineSnapshot.model_validate(values)


def _change(
    old_paragraph: str,
    new_paragraph: str,
    *,
    n: int,
) -> Any:
    return normalize_reviewed_change(
        _proposal(
            proposal_id=f"00000000-0000-0000-0000-0000000001{n:02d}",
            decision_id=f"00000000-0000-0000-0000-0000000002{n:02d}",
            old_paragraph=old_paragraph,
            new_paragraph=new_paragraph,
            superdocs_change_id=f"change-{n}",
            chunk_id=f"chunk-{n}",
        )
    )


def _compile(changes: Sequence[Any], baseline: BaselineSnapshot):
    mapped = tuple(changes)
    proof = map_approved_replacements(mapped, baseline, NOW)
    plan = compile_write_plan(
        mapped=mapped,
        baseline=baseline,
        proof=proof,
        sync_run_id=UUID("00000000-0000-0000-0000-000000000301"),
        rule_identity=UUID("00000000-0000-0000-0000-000000000302"),
        rule_version=1,
        instruction_sha256=ZERO_HASH,
        configuration_sha256=ONE_HASH,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=24),
    )
    return proof, plan


def _request_indexes(plan) -> list[tuple[int, int, str]]:
    requests = plan.payload.provider_operations[0].requests
    pairs: list[tuple[int, int, str]] = []
    for index in range(0, len(requests), 2):
        delete_range = requests[index]["deleteContentRange"]["range"]
        insert = requests[index + 1]["insertText"]
        pairs.append(
            (
                int(delete_range["startIndex"]),
                int(delete_range["endIndex"]),
                str(insert["text"]),
            )
        )
    return pairs


def test_single_approved_replacement_still_compiles() -> None:
    change = _change(PAYMENT, PAYMENT_14, n=1)
    baseline = _baseline(_canonical((PAYMENT, WARRANTY, SUPPORT)))
    proof, plan = _compile((change,), baseline)

    assert tuple(item.lineage.proposal_id for item in proof.payload.replacements) == (
        change.proposal_id,
    )
    assert plan.payload.expected_replacement.old_text == "30"
    assert plan.payload.expected_replacement.new_text == "14"
    assert len(plan.payload.planned_replacements) == 1
    assert len(plan.payload.provider_operations[0].requests) == 2
    assert plan.payload.provider_operations[0].required_revision_id == "revision-A"
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical((PAYMENT_14, WARRANTY, SUPPORT))
    )


def test_two_non_overlapping_replacements_are_planned_high_to_low() -> None:
    payment = _change(PAYMENT, PAYMENT_14, n=1)
    warranty = _change(WARRANTY, WARRANTY_24, n=2)
    baseline = _baseline(_canonical((PAYMENT, WARRANTY, SUPPORT)))
    proof, plan = _compile((warranty, payment), baseline)

    assert tuple(item.lineage.proposal_id for item in proof.payload.replacements) == (
        payment.proposal_id,
        warranty.proposal_id,
    )
    assert tuple(item.proposal_id for item in plan.payload.planned_replacements) == (
        payment.proposal_id,
        warranty.proposal_id,
    )
    assert _request_indexes(plan) == [(43, 45, "24"), (19, 21, "14")]
    rejected = UUID("00000000-0000-0000-0000-000000000199")
    serialized = f"{proof.payload.model_dump(mode='json')}{plan.payload.model_dump(mode='json')}"
    assert str(rejected) not in serialized
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical((PAYMENT_14, WARRANTY_24, SUPPORT))
    )


def test_equal_length_grow_shrink_and_mixed_deltas_keep_later_indexes_correct() -> None:
    equal_a = _change(PAYMENT, PAYMENT_14, n=1)
    equal_b = _change(WARRANTY, WARRANTY_24, n=2)
    grow = _change(PAYMENT, "Payment terms are 14 calendar days.", n=3)
    shrink = _change(WARRANTY, "Warranty lasts 6 months.", n=4)
    third = _change(SUPPORT, "Support hours are 10 to 5.", n=5)
    baseline = _baseline(_canonical((PAYMENT, WARRANTY, SUPPORT)))

    _, equal_plan = _compile((equal_a, equal_b), baseline)
    assert _request_indexes(equal_plan) == [(43, 45, "24"), (19, 21, "14")]
    assert equal_plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical((PAYMENT_14, WARRANTY_24, SUPPORT))
    )

    _, grow_plan = _compile((grow, equal_b), baseline)
    assert _request_indexes(grow_plan) == [(43, 45, "24"), (19, 21, "14 calendar")]
    assert grow_plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical(("Payment terms are 14 calendar days.", WARRANTY_24, SUPPORT))
    )

    _, shrink_plan = _compile((equal_a, shrink), baseline)
    assert _request_indexes(shrink_plan) == [(43, 45, "6"), (19, 21, "14")]
    assert shrink_plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical((PAYMENT_14, "Warranty lasts 6 months.", SUPPORT))
    )

    _, mixed_plan = _compile((grow, shrink, third), baseline)
    assert _request_indexes(mixed_plan) == [
        (72, 73, "10"),
        (43, 45, "6"),
        (19, 21, "14 calendar"),
    ]
    assert mixed_plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical(
            (
                "Payment terms are 14 calendar days.",
                "Warranty lasts 6 months.",
                "Support hours are 10 to 5.",
            )
        )
    )


def test_adjacent_non_overlapping_ranges_are_supported() -> None:
    paragraph = "Keep AAABBB here."
    first = _change(paragraph, "Keep XXXBBB here.", n=1)
    second = _change(paragraph, "Keep AAAYYY here.", n=2)
    baseline = _baseline(_canonical((paragraph,)))
    proof, plan = _compile((first, second), baseline)

    ranges = [
        (item.location.edit_start_index, item.location.edit_end_index)
        for item in proof.payload.replacements
    ]
    assert ranges[0][1] == ranges[1][0]
    assert plan.payload.expected_postimage.canonical_sha256 == sha256_json(
        _canonical(("Keep XXXYYY here.",))
    )


def test_overlapping_and_duplicate_mapped_ranges_fail_closed() -> None:
    overlap_a = _change(PAYMENT, "Payment terms are 14 days.", n=1)
    overlap_b = _change(PAYMENT, "Payment terms are 14 days now.", n=2)
    duplicate_a = _change(PAYMENT, PAYMENT_14, n=3)
    duplicate_b = _change(PAYMENT, "Payment terms are 88 days.", n=4)
    baseline = _baseline(_canonical((PAYMENT, WARRANTY)))

    with pytest.raises(MappingFailure) as overlap:
        map_approved_replacements((overlap_a, overlap_b), baseline, NOW)
    assert overlap.value.code is MappingFailureCode.OVERLAPPING_MAPPED_RANGES

    with pytest.raises(MappingFailure) as duplicate:
        map_approved_replacements((duplicate_a, duplicate_b), baseline, NOW)
    assert duplicate.value.code is MappingFailureCode.DUPLICATE_TARGET_MAPPING


def test_one_unsupported_approved_proposal_fails_the_entire_mapped_set() -> None:
    supported = _change(PAYMENT, PAYMENT_14, n=1)
    missing = _change("This sentence is absent.", "This sentence is rewritten.", n=2)
    baseline = _baseline(_canonical((PAYMENT, WARRANTY, SUPPORT)))

    with pytest.raises(MappingFailure) as error:
        map_approved_replacements((supported, missing), baseline, NOW)
    assert error.value.code is MappingFailureCode.PREIMAGE_MISSING
    assert error.value.proposal_id == missing.proposal_id
    assert f"approved proposal {missing.proposal_id}" in error.value.safe_message


def test_mixed_source_revisions_fail_closed() -> None:
    payment = _change(PAYMENT, PAYMENT_14, n=1)
    warranty = _change(WARRANTY, WARRANTY_24, n=2)
    first = map_replacement(payment, _baseline(_canonical((PAYMENT, WARRANTY))), NOW)
    second = map_replacement(
        warranty,
        _baseline(
            _canonical((PAYMENT, WARRANTY)),
            snapshot_id=UUID("00000000-0000-0000-0000-000000000299"),
            baseline_revision_id="revision-B",
            run_baseline_revision_id="revision-B",
            capture_revision_id="revision-B",
        ),
        NOW,
    )
    with pytest.raises(MappingFailure) as error:
        seal_mapped_set((first, second), created_at=NOW)
    assert error.value.code is MappingFailureCode.STALE_LINEAGE


@dataclass(frozen=True)
class _ProposalSpec:
    old_paragraph: str
    new_paragraph: str
    decision: ChangeDecision
    operation: ProposalOperation = ProposalOperation.EDIT
    old_html: str | None = None
    new_html: str | None = None


async def _seed_run(
    paragraphs: Sequence[str],
    specs: Sequence[_ProposalSpec],
) -> tuple[Any, Any, InMemoryArtifactStore, UUID, tuple[UUID, ...]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    canonical = _canonical(paragraphs)
    canonical_hash = sha256_json(canonical)
    export_content = b"PK\x03\x04reviewed multi-write export"
    export_sha256 = sha256(export_content).hexdigest()
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
            mime_type=GOOGLE_DOC_MIME,
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
                "instruction": "Change payment and warranty terms.",
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
            source_format=GOOGLE_DOC_MIME,
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
            raw_pending_evidence={"change_ids": [f"change-{index}" for index in range(len(specs))]},
            resolution=ReviewRoundResolution.SUBMIT_CHANGES,
            resolved_by_subject="owner-a",
            resolved_at=NOW,
        )
        session.add(review_round)
        await session.flush()
        proposal_ids: list[UUID] = []
        for index, spec in enumerate(specs, start=1):
            if spec.operation is ProposalOperation.CREATE:
                old_html = spec.old_html
                new_html = spec.new_html or spec.new_paragraph
                chunk_id = None
            else:
                old_html = spec.old_html or f"<p>{spec.old_paragraph}</p>"
                new_html = spec.new_html or f"<p>{spec.new_paragraph}</p>"
                chunk_id = f"chunk-{index}"
            proposal = ProposedChange(
                sync_run_id=run.id,
                superdocs_job_id=job.id,
                review_round_id=review_round.id,
                target_document_id=superdocs_document.id,
                superdocs_change_id=f"change-{index}",
                ordinal=index,
                operation=spec.operation,
                chunk_id=chunk_id,
                old_html=old_html,
                new_html=new_html,
                payload_sha256=f"{index + 7:x}" * 64,
                raw_payload={"operation": spec.operation.value},
            )
            session.add(proposal)
            await session.flush()
            proposal_ids.append(proposal.id)
            session.add(
                ReviewDecision(
                    sync_run_id=run.id,
                    proposed_change_id=proposal.id,
                    decision=spec.decision,
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
                artifact_reference="exports/run-a.docx",
                sha256=export_sha256,
                size_bytes=len(export_content),
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                warnings=[],
                final_version_id="final-a",
                # Production plans expire 24 hours after export. Keep the integration
                # fixture current instead of coupling it to the historical proof timestamp.
                exported_at=datetime.now(UTC),
            )
        )
        await session.commit()
        run_id = run.id
    return engine, sessions, artifacts, run_id, tuple(proposal_ids)


def _planning_service(sessions: Any, artifacts: InMemoryArtifactStore) -> WritePlanningService:
    return WritePlanningService(sessions=sessions, owner_subject="owner-a", artifacts=artifacts)


async def _assert_approved_only(
    sessions: Any,
    approved_ids: Sequence[UUID],
    rejected_ids: Sequence[UUID],
) -> None:
    async with sessions() as session:
        proofs = tuple(await session.scalars(select(MappingProof)))
        plans = tuple(await session.scalars(select(WritePlan)))
        lineage = tuple(await session.scalars(select(WritePlanLineage)))
    assert len(proofs) == len(plans) == 1
    assert len(lineage) == len(approved_ids)
    proof_ids = [
        UUID(item["lineage"]["proposal_id"]) for item in proofs[0].proof_payload["replacements"]
    ]
    plan_ids = [UUID(item["proposal_id"]) for item in plans[0].payload["approval_lineage"]]
    assert proof_ids == plan_ids == list(approved_ids)
    serialized = f"{proofs[0].proof_payload}{plans[0].payload}"
    assert all(str(rejected_id) not in serialized for rejected_id in rejected_ids)


async def test_approve_one_reject_one_maps_only_the_approved_proposal() -> None:
    engine, sessions, artifacts, run_id, ids = await _seed_run(
        (PAYMENT, WARRANTY, SUPPORT),
        (
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.REJECT),
        ),
    )
    service = _planning_service(sessions, artifacts)
    first = await service.dry_run(run_id)
    second = await service.dry_run(run_id)
    assert first.status is DryRunStatus.READY
    assert first == second
    assert [change.proposal_id for change in first.changes] == [ids[0]]
    assert first.old_text == "30"
    await _assert_approved_only(sessions, (ids[0],), (ids[1],))
    await engine.dispose()


async def test_approve_two_and_reject_third_plans_only_approved() -> None:
    engine, sessions, artifacts, run_id, ids = await _seed_run(
        (PAYMENT, WARRANTY, SUPPORT),
        (
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
            _ProposalSpec(SUPPORT, SUPPORT_86, ChangeDecision.REJECT),
        ),
    )
    view = await _planning_service(sessions, artifacts).dry_run(run_id)
    assert view.status is DryRunStatus.READY
    assert [change.proposal_id for change in view.changes] == [ids[0], ids[1]]
    assert view.operation_count == 4
    assert "independent non-overlapping replacements" in " ".join(view.why_safe)
    await _assert_approved_only(sessions, (ids[0], ids[1]), (ids[2],))
    await engine.dispose()


async def test_all_rejected_is_a_safe_stop_with_no_plan() -> None:
    engine, sessions, artifacts, run_id, _ids = await _seed_run(
        (PAYMENT, WARRANTY),
        (
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.REJECT),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.REJECT),
        ),
    )
    view = await _planning_service(sessions, artifacts).dry_run(run_id)
    assert view.status is DryRunStatus.NOT_APPROVED
    assert view.reason_code == "NOT_APPROVED"
    async with sessions() as session:
        assert tuple(await session.scalars(select(MappingProof))) == ()
        assert tuple(await session.scalars(select(WritePlan))) == ()
    await engine.dispose()


async def test_approved_create_with_supported_edit_fails_the_whole_plan() -> None:
    engine, sessions, artifacts, run_id, ids = await _seed_run(
        (PAYMENT, WARRANTY),
        (
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(
                "",
                "",
                ChangeDecision.APPROVE,
                operation=ProposalOperation.CREATE,
                old_html=None,
                new_html="<p>Added signature block.</p>",
            ),
        ),
    )
    view = await _planning_service(sessions, artifacts).dry_run(run_id)
    assert view.status is DryRunStatus.UNSUPPORTED
    assert view.reason_code == "UNSUPPORTED_OPERATION"
    assert view.proposal_id == ids[1]
    assert f"approved proposal {ids[1]}" in (view.reason or "")
    async with sessions() as session:
        assert tuple(await session.scalars(select(WritePlan))) == ()
        assert tuple(await session.scalars(select(ExternalEffect))) == ()
    await engine.dispose()


async def test_rejected_unsupported_create_does_not_block_approved_edit() -> None:
    engine, sessions, artifacts, run_id, ids = await _seed_run(
        (PAYMENT, WARRANTY),
        (
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(
                "",
                "",
                ChangeDecision.REJECT,
                operation=ProposalOperation.CREATE,
                old_html=None,
                new_html="<p>Added signature block.</p>",
            ),
        ),
    )
    view = await _planning_service(sessions, artifacts).dry_run(run_id)
    assert view.status is DryRunStatus.READY
    assert [change.proposal_id for change in view.changes] == [ids[0]]
    await _assert_approved_only(sessions, (ids[0],), (ids[1],))
    await engine.dispose()


@asynccontextmanager
async def _write_environment(
    *,
    expected_paragraphs: Sequence[str],
    specs: Sequence[_ProposalSpec],
    paragraphs: Sequence[str] = (PAYMENT, WARRANTY, SUPPORT),
):
    engine, sessions, artifacts, run_id, ids = await _seed_run(paragraphs, specs)
    dry_run = await _planning_service(sessions, artifacts).dry_run(run_id)
    assert dry_run.status is DryRunStatus.READY
    baseline = _canonical(paragraphs)
    expected = _canonical(expected_paragraphs)
    async with sessions() as session:
        plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run_id))
        assert plan is not None
        assert sha256_json(expected) == plan.expected_postimage_sha256
    provider = FakeGoogleWriteProvider(baseline, expected)
    service = WriteBackService(
        sessions=sessions,
        owner_subject="owner-a",
        provider_factory=lambda _session, _connection_id: provider,
        artifacts=artifacts,
    )
    try:
        yield sessions, service, provider, run_id, ids, dry_run, expected, artifacts
    finally:
        await engine.dispose()


async def test_stale_google_revision_does_not_mutate() -> None:
    async with _write_environment(
        expected_paragraphs=(PAYMENT_14, WARRANTY_24, SUPPORT),
        specs=(
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
        ),
    ) as (_sessions, service, provider, run_id, _ids, _dry_run, _expected, _artifacts):
        provider.revision = "revision-human"
        provider.current = _canonical((PAYMENT, "Human edited warranty.", SUPPORT))
        result = await service.execute(run_id)
        assert result.status is WriteBackStatus.CONFLICT
        assert result.conflict is not None
        assert result.conflict.detection_stage == "BEFORE_BACKUP"
        assert provider.copy_calls == provider.commit_calls == 0


async def test_concurrent_human_edit_after_backup_does_not_clobber() -> None:
    async with _write_environment(
        expected_paragraphs=(PAYMENT_14, WARRANTY_24, SUPPORT),
        specs=(
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
        ),
    ) as (_sessions, service, provider, run_id, _ids, _dry_run, _expected, _artifacts):
        inner = provider.create_backup

        async def create_backup_and_tamper(**kwargs: Any) -> Any:
            receipt = await inner(**kwargs)
            provider.current = _canonical((PAYMENT, "Human edited warranty.", SUPPORT))
            provider.revision = "revision-human"
            return receipt

        provider.create_backup = create_backup_and_tamper  # type: ignore[method-assign]
        result = await service.execute(run_id)
        assert result.status is WriteBackStatus.CONFLICT
        assert result.conflict is not None
        assert result.conflict.detection_stage == "AFTER_BACKUP"
        assert provider.copy_calls == 1
        assert provider.commit_calls == 0


async def test_backup_precedes_required_revision_write_and_complete_postimage() -> None:
    async with _write_environment(
        expected_paragraphs=(PAYMENT_14, WARRANTY_24, SUPPORT),
        specs=(
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
        ),
    ) as (sessions, service, provider, run_id, ids, dry_run, expected, _artifacts):
        result = await service.execute(run_id)
        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert result.structurally_verified is True
        assert result.verified_preview is not None
        assert [block.text for block in result.verified_preview.blocks] == [
            PAYMENT_14,
            WARRANTY_24,
            SUPPORT,
        ]
        assert provider.events == [
            "read",
            "copy",
            "verify-backup",
            "read",
            "batch-update",
            "read",
        ]
        assert provider.commit_calls == 1
        operation = provider.operations[0]
        assert operation.required_revision_id == "revision-A"
        payload = operation.provider_payload()
        assert payload["writeControl"] == {"requiredRevisionId": "revision-A"}
        assert len(payload["requests"]) == 4
        assert dry_run.changes[0].proposal_id == ids[0]
        assert dry_run.changes[1].proposal_id == ids[1]
        async with sessions() as session:
            run = await session.get(SyncRun, run_id)
            assert run is not None
            summary = await get_write_back_summary(session, run)
            verification = await session.scalar(select(VerificationResult))
        assert summary is not None
        assert summary.preview is not None
        assert tuple(item.old_text for item in summary.preview.changes) == ("30", "12")
        assert tuple(item.new_text for item in summary.preview.changes) == ("14", "24")
        assert verification is not None
        assert verification.report["complete_structure_matches"] is True
        assert sha256_json(provider.current) == sha256_json(expected)


async def test_corrupted_postimage_is_never_write_verified() -> None:
    async with _write_environment(
        expected_paragraphs=(PAYMENT_14, WARRANTY_24, SUPPORT),
        specs=(
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
        ),
    ) as (_sessions, service, provider, run_id, _ids, _dry_run, _expected, _artifacts):
        provider.expected = _canonical((PAYMENT_14, WARRANTY, SUPPORT))
        result = await service.execute(run_id)
        assert result.status is WriteBackStatus.VERIFICATION_FAILED
        assert result.structurally_verified is False
        assert result.attention_code == "GOOGLE_POSTIMAGE_VERIFICATION_FAILED"


async def test_decision_replay_is_idempotent_and_retry_cannot_duplicate_google() -> None:
    async with _write_environment(
        expected_paragraphs=(PAYMENT_14, WARRANTY_24, SUPPORT),
        specs=(
            _ProposalSpec(PAYMENT, PAYMENT_14, ChangeDecision.APPROVE),
            _ProposalSpec(WARRANTY, WARRANTY_24, ChangeDecision.APPROVE),
        ),
    ) as (sessions, service, provider, run_id, _ids, dry_run, _expected, artifacts):
        replay = await WritePlanningService(
            sessions=sessions,
            owner_subject="owner-a",
            artifacts=artifacts,
        ).dry_run(run_id)
        assert replay == dry_run
        first = await service.execute(run_id)
        second = await service.execute(run_id)
        assert first.status is second.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == provider.commit_calls == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(WritePlan)) == 1
            assert await session.scalar(select(func.count()).select_from(MappingProof)) == 1
            assert await session.scalar(select(func.count()).select_from(ExternalEffect)) == 2
