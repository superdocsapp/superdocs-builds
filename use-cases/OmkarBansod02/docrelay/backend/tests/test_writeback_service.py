import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
    WatchScanStatus,
    WatchScanTrigger,
    WatchVersionStatus,
    WriteAuthorizationState,
)
from docrelay.integrations.google.canonical import sha256_json
from docrelay.integrations.google.contracts import (
    BackupReceipt,
    BackupVerification,
    CommitClassification,
    CurrentGoogleDocument,
    GoogleCapabilities,
    GoogleFileIdentity,
    GuardedCommitResult,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.write_back import GoogleEffectOutcomeUnknown
from docrelay.persistence.base import Base
from docrelay.persistence.models import (
    Backup,
    CloudConnection,
    CloudDocument,
    ExternalEffect,
    FolderRule,
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
    WatchConfig,
    WatchDocumentVersion,
    WatchedItem,
    WatchRunLink,
    WatchScan,
    WriteConflict,
    WritePlan,
)
from docrelay.services.artifacts import InMemoryArtifactStore
from docrelay.services.superdocs_workflow import get_write_back_summary
from docrelay.services.write_planning import DryRunStatus, WritePlanningService
from docrelay.services.writeback import (
    ConflictChoice,
    ExactFileWriteAuthorizationRequired,
    WatchedFileOutOfScope,
    WriteBackNotEligible,
    WriteBackService,
    WriteBackStatus,
    _shift_body_indexes,
)

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


class MutableArtifactStore(InMemoryArtifactStore):
    corrupt_reads = False

    async def read(self, reference: str) -> bytes:
        content = await super().read(reference)
        return b"tampered reviewed export" if self.corrupt_reads else content


def _canonical(token: str, *, neighbor: str = "Unchanged neighbor.\n") -> dict[str, Any]:
    target_text = f"Payment is due within {token} days.\n"
    target_end = 162 + len(target_text.encode("utf-16-le")) // 2
    trailing_text = "Trailing content stays exact.\n"
    token_delta = len(token.encode("utf-16-le")) // 2 - 2
    trailing_start = 220 + token_delta
    trailing_end = trailing_start + len(trailing_text.encode("utf-16-le")) // 2
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
                        "startIndex": 130,
                        "endIndex": 150,
                        "type": "paragraph",
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": None,
                        "positionedObjectIds": [],
                        "runs": [
                            {
                                "kind": "text",
                                "startIndex": 130,
                                "endIndex": 150,
                                "text": neighbor,
                                "style": {},
                            }
                        ],
                    },
                    {
                        "startIndex": 162,
                        "endIndex": target_end,
                        "type": "paragraph",
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": None,
                        "positionedObjectIds": [],
                        "runs": [
                            {
                                "kind": "text",
                                "startIndex": 162,
                                "endIndex": target_end,
                                "text": target_text,
                                "style": {},
                            }
                        ],
                    },
                    {
                        "startIndex": trailing_start,
                        "endIndex": trailing_end,
                        "type": "paragraph",
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": None,
                        "positionedObjectIds": [],
                        "runs": [
                            {
                                "kind": "text",
                                "startIndex": trailing_start,
                                "endIndex": trailing_end,
                                "text": trailing_text,
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


def _fresh_live_canonical(token: str) -> dict[str, Any]:
    """Sanitized structural fixture from live run 85919382 on 2026-08-13."""
    target_text = f"Payment is due within {token} days.\n"
    target_end = 34 + len(target_text.encode("utf-16-le")) // 2
    return {
        "schema": "docrelay.google-native-canonical.v1",
        "tabs": [
            {
                "tabProperties": {
                    "tabId": "t.0",
                    "title": "Tab 1",
                    "index": 0,
                    "nestingLevel": None,
                    "parentTabId": None,
                },
                "body": [
                    {
                        "startIndex": None,
                        "endIndex": 1,
                        "type": "sectionBreak",
                        "sectionStyle": {
                            "sectionType": "CONTINUOUS",
                            "contentDirection": "LEFT_TO_RIGHT",
                            "columnSeparatorStyle": "NONE",
                        },
                    },
                    _plain_paragraph(1, "Vendor Agreement\n"),
                    _plain_paragraph(18, "\n"),
                    _plain_paragraph(19, "Payment Terms\n"),
                    _plain_paragraph(33, "\n"),
                    _plain_paragraph(34, target_text),
                    _plain_paragraph(target_end, "\n"),
                    _plain_paragraph(target_end + 1, "Support\n"),
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


def _plain_paragraph(start: int, text: str) -> dict[str, Any]:
    end = start + len(text.encode("utf-16-le")) // 2
    return {
        "startIndex": start,
        "endIndex": end,
        "type": "paragraph",
        "paragraphStyle": {
            "direction": "LEFT_TO_RIGHT",
            "namedStyleType": "NORMAL_TEXT",
        },
        "bullet": None,
        "positionedObjectIds": [],
        "runs": [
            {
                "kind": "text",
                "startIndex": start,
                "endIndex": end,
                "text": text,
                "style": {},
            }
        ],
    }


class FakeGoogleWriteProvider:
    def __init__(self, baseline: dict[str, Any], expected: dict[str, Any]) -> None:
        self.baseline = baseline
        self.expected = expected
        self.current = baseline
        self.revision = "revision-A"
        self.backup_verification = BackupVerification(
            independently_readable=True,
            separate_file=True,
            expected_mime_type=True,
            expected_location=True,
            content_matches_baseline=True,
            acl_not_broader=True,
            canonical_sha256=sha256_json(baseline),
            evidence={"permission_comparison": "not_broader"},
        )
        self.commit_result = GuardedCommitResult(
            classification=CommitClassification.SUCCEEDED,
            resulting_revision_id="revision-B",
        )
        self.copy_unknown = False
        self.commit_unknown = False
        self.change_after_backup = False
        self.unknown_postimage: dict[str, Any] | None = None
        self.unknown_revision = "revision-B"
        self.block_copy: asyncio.Event | None = None
        self.copy_entered = asyncio.Event()
        self.events: list[str] = []
        self.copy_calls = 0
        self.verify_calls = 0
        self.verify_error: GoogleIntegrationError | None = None
        self.commit_error: GoogleIntegrationError | None = None
        self.commit_calls = 0
        self.operations: list[object] = []
        self.is_app_authorized = True
        self.watched_path_verified = True
        self.move_outside_before_commit = False
        self.move_outside_after_commit = False

    async def inspect_current(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> CurrentGoogleDocument:
        self.events.append("read")
        if watched_root_id is not None:
            assert watched_ancestor_folder_ids
            assert watched_ancestor_folder_ids[0] == watched_root_id
            assert watched_ancestor_folder_ids[-1] == destination_parent_id
        return CurrentGoogleDocument(
            identity=GoogleFileIdentity(
                file_id=file_id,
                parent_ids=(destination_parent_id,),
                mime_type=GOOGLE_DOC_MIME,
            ),
            name="Synthetic contract",
            revision_id=self.revision,
            native_raw_sha256="1" * 64,
            canonical_schema_version="docrelay.google-native-canonical.v1",
            canonical_sha256=sha256_json(self.current),
            canonical_payload=self.current,
            capabilities=GoogleCapabilities(
                can_edit=True,
                can_modify_content=True,
                can_download=True,
                can_copy=True,
                destination_can_add_children=True,
            ),
            safe_provider_metadata={
                "trashed": False,
                "is_app_authorized": self.is_app_authorized,
                "watched_path_verified": (
                    self.watched_path_verified if watched_root_id is not None else None
                ),
            },
        )

    async def create_backup(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        backup_name: str,
        operation_metadata: dict[str, str],
    ) -> BackupReceipt:
        self.events.append("copy")
        self.copy_calls += 1
        self.copy_entered.set()
        if self.block_copy is not None:
            await self.block_copy.wait()
        if self.copy_unknown:
            raise GoogleEffectOutcomeUnknown("backup response was not received")
        if self.change_after_backup:
            self.current = _canonical("45", neighbor="Human edit retained.\n")
            self.revision = "revision-human"
        assert "DocRelay backup" in backup_name
        assert operation_metadata["source_revision"] == "revision-A"
        return BackupReceipt(
            backup_file_id="backup-file-1",
            parent_ids=(destination_parent_id,),
            provider_metadata={"mime_type": GOOGLE_DOC_MIME},
        )

    async def verify_backup(
        self,
        *,
        source_file_id: str,
        backup_file_id: str,
        expected_parent_id: str,
        expected_baseline_sha256: str,
    ) -> BackupVerification:
        self.events.append("verify-backup")
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error
        assert source_file_id != backup_file_id
        assert expected_baseline_sha256 == sha256_json(self.baseline)
        return self.backup_verification

    async def commit_guarded(
        self,
        *,
        file_id: str,
        operation: object,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> GuardedCommitResult:
        self.events.append("batch-update")
        self.commit_calls += 1
        self.operations.append(operation)
        if watched_root_id is not None:
            assert watched_ancestor_folder_ids
            assert watched_ancestor_folder_ids[0] == watched_root_id
        if self.move_outside_before_commit:
            self.watched_path_verified = False
            return GuardedCommitResult(
                classification=CommitClassification.DEFINITELY_NOT_APPLIED,
                safe_provider_evidence={
                    "watched_path_verified": False,
                    "batch_update_sent": False,
                },
            )
        if self.commit_error is not None:
            error = self.commit_error
            self.commit_error = None
            raise error
        if self.commit_unknown:
            self.current = self.unknown_postimage or self.expected
            self.revision = self.unknown_revision
            raise GoogleEffectOutcomeUnknown("batchUpdate response was not received")
        if self.commit_result.classification is CommitClassification.SUCCEEDED:
            self.current = self.expected
            self.revision = self.commit_result.resulting_revision_id or "revision-B"
            if self.move_outside_after_commit:
                self.watched_path_verified = False
        return self.commit_result


@asynccontextmanager
async def _environment(
    *,
    watched: bool = False,
    old_token: str = "45",
    new_token: str = "30",
    tamper_export_after_plan: bool = False,
    fresh_live_snapshot: bool = False,
) -> AsyncIterator[
    tuple[
        async_sessionmaker[Any],
        WriteBackService,
        FakeGoogleWriteProvider,
        Any,
        dict[str, Any],
        dict[str, Any],
    ]
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
    now = datetime.now(UTC)
    baseline = _fresh_live_canonical(old_token) if fresh_live_snapshot else _canonical(old_token)
    baseline_hash = sha256_json(baseline)
    export_content = b"PK\x03\x04reviewed write-back evidence"
    export_sha256 = hashlib.sha256(export_content).hexdigest()
    artifacts = MutableArtifactStore()
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
            display_name="Synthetic contract",
            parent_ids=["parent-a"],
            last_seen_revision_id="revision-A",
        )
        session.add(document)
        await session.flush()
        rule = None
        watch = None
        if watched:
            watch = WatchConfig(
                connection_id=connection.id,
                parent_folder_id="parent-a",
                root_name="Parent A",
                schedule="interval",
                timezone="UTC",
                interval_seconds=300,
                default_mode=SyncMode.PREVIEW,
                enabled=True,
                next_scan_at=now,
            )
            session.add(watch)
            await session.flush()
            rule = FolderRule(
                watch_config_id=watch.id,
                provider_folder_id="parent-a",
                version=1,
                instruction=f"Change {old_token} days to {new_token} days.",
                instruction_sha256="3" * 64,
                configuration={"precedence": "nearest_enabled_ancestor"},
                supported_formats={"mime_types": [GOOGLE_DOC_MIME]},
                active=True,
            )
            session.add(rule)
            await session.flush()
        capture = GoogleBaselineCapture(
            cloud_document_id=document.id,
            provider_revision_id="revision-A",
            native_raw_sha256="1" * 64,
            native_canonical_sha256=baseline_hash,
            exported_docx_sha256="2" * 64,
            exported_docx_size_bytes=9000,
            canonicalizer_version="docrelay.google-native-canonical.v1",
            canonical_payload=baseline,
            capability_evidence={"canModifyContent": True},
            parent_ids=["parent-a"],
            attempt_count=1,
            capture_started_at=now,
            captured_at=now,
            provider_evidence={"read_only": True},
        )
        session.add(capture)
        await session.flush()
        run = SyncRun(
            cloud_document_id=document.id,
            folder_rule_id=rule.id if rule is not None else None,
            folder_rule_version=rule.version if rule is not None else None,
            rule_snapshot={
                "instruction": f"Change {old_token} days to {new_token} days.",
                "instruction_sha256": "3" * 64,
                **(
                    {
                        "root_folder_id": "parent-a",
                        "document_ancestor_folder_ids": ["parent-a"],
                    }
                    if watched
                    else {}
                ),
            },
            mode=SyncMode.PREVIEW,
            state=SyncRunState.REVIEWED_EXPORT_READY,
            state_version=7,
            intent_key="4" * 64,
            baseline_revision_id="revision-A",
            started_at=now,
        )
        session.add(run)
        await session.flush()
        if watch is not None and rule is not None:
            watch_scan = WatchScan(
                watch_config_id=watch.id,
                trigger=WatchScanTrigger.SCHEDULED,
                status=WatchScanStatus.SUCCEEDED,
                active_key=None,
                lease_token=run.id,
                lease_expires_at=now,
                claim_generation=1,
                started_at=now,
                completed_at=now,
                discovered_count=1,
                enqueued_count=1,
            )
            session.add(watch_scan)
            await session.flush()
            watched_item = WatchedItem(
                watch_config_id=watch.id,
                provider_file_id=document.provider_file_id,
                cloud_document_id=document.id,
                display_name="Synthetic contract",
                mime_type=GOOGLE_DOC_MIME,
                provider_version="1",
                parent_folder_id="parent-a",
                ancestor_folder_ids=["parent-a"],
                current_in_scope=True,
                last_seen_scan_id=watch_scan.id,
                last_seen_at=now,
                last_enqueued_provider_version="1",
                last_enqueued_revision_id="revision-A",
                last_enqueued_run_id=run.id,
                write_authorization_state=WriteAuthorizationState.REQUIRED,
                write_authorization_checked_at=now,
            )
            session.add(watched_item)
            await session.flush()
            watched_version = WatchDocumentVersion(
                watched_item_id=watched_item.id,
                first_seen_scan_id=watch_scan.id,
                provider_version="1",
                status=WatchVersionStatus.ENQUEUED,
                provider_revision_id="revision-A",
                folder_rule_id=rule.id,
                folder_rule_version=rule.version,
                rule_snapshot=dict(run.rule_snapshot),
                sync_run_id=run.id,
            )
            session.add(watched_version)
            await session.flush()
            session.add(
                WatchRunLink(
                    watch_config_id=watch.id,
                    watch_scan_id=watch_scan.id,
                    watched_item_id=watched_item.id,
                    watch_document_version_id=watched_version.id,
                    sync_run_id=run.id,
                    folder_rule_id=rule.id,
                    folder_rule_version=rule.version,
                    rule_snapshot=dict(run.rule_snapshot),
                    write_authorization_state=WriteAuthorizationState.REQUIRED,
                    write_authorization_checked_at=now,
                    write_authorization_evidence={
                        "is_app_authorized": False,
                        "read_scope_is_not_write_authority": True,
                    },
                )
            )
        snapshot = SourceSnapshot(
            sync_run_id=run.id,
            cloud_document_id=document.id,
            provider_revision_id="revision-A",
            source_format=GOOGLE_DOC_MIME,
            captured_at=now,
            native_raw_sha256="1" * 64,
            native_canonical_sha256=baseline_hash,
            exported_artifact_sha256="5" * 64,
            artifact_reference="baselines/run-a.docx",
            schema_version="docrelay.google-native-canonical.v1",
            capability_evidence={"canModifyContent": True},
            provider_evidence={"selected_baseline_capture_id": str(capture.id)},
        )
        session.add(snapshot)
        await session.flush()
        sd_session = SuperDocsSession(
            sync_run_id=run.id,
            session_id="session-a",
            raw_evidence={"fresh_ingestion": True},
        )
        session.add(sd_session)
        await session.flush()
        sd_document = SuperDocsDocument(
            superdocs_session_id=sd_session.id,
            source_snapshot_id=snapshot.id,
            role=SuperDocsDocumentRole.TARGET,
            session_document_id="document-a",
            durable_document_id="durable-a",
            upload_version_id="upload-a",
            final_version_id="final-a",
            baseline_html_sha256="6" * 64,
            baseline_evidence={"fresh": True},
        )
        session.add(sd_document)
        await session.flush()
        job = SuperDocsJob(
            sync_run_id=run.id,
            superdocs_session_id=sd_session.id,
            target_document_id=sd_document.id,
            provider_job_id="job-a",
            status=SuperDocsJobStatus.COMPLETED,
            start_request_sha256="7" * 64,
            raw_state={"status": "completed"},
            usage_evidence={"ops_charged": 1},
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
            raw_pending_evidence={"change_ids": ["change-a"]},
            resolution=ReviewRoundResolution.SUBMIT_CHANGES,
            resolved_by_subject="owner-a",
            resolved_at=now,
        )
        session.add(review_round)
        await session.flush()
        proposal = ProposedChange(
            sync_run_id=run.id,
            superdocs_job_id=job.id,
            review_round_id=review_round.id,
            target_document_id=sd_document.id,
            superdocs_change_id="change-a",
            ordinal=1,
            operation=ProposalOperation.EDIT,
            chunk_id="ephemeral-chunk-a",
            old_html=f"<p>Payment is due within {old_token} days.</p>",
            new_html=f"<p>Payment is due within {new_token} days.</p>",
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
                superdocs_session_id=sd_session.id,
                superdocs_document_id=sd_document.id,
                superdocs_job_id=job.id,
                artifact_reference="exports/run-a.docx",
                sha256=export_sha256,
                size_bytes=len(export_content),
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                warnings=[],
                final_version_id="final-a",
                exported_at=now,
            )
        )
        await session.commit()
        run_id = run.id
        proposal_id = proposal.id

    dry_run = await WritePlanningService(
        sessions=sessions,
        owner_subject="owner-a",
        artifacts=artifacts,
    ).dry_run(run_id, proposal_id=proposal_id)
    assert dry_run.status is DryRunStatus.READY
    async with sessions() as session:
        from docrelay.persistence.models import WritePlan

        plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run_id))
        assert plan is not None
        expected = (
            _fresh_live_canonical(new_token) if fresh_live_snapshot else _canonical(new_token)
        )
        assert sha256_json(expected) == plan.expected_postimage_sha256

    provider = FakeGoogleWriteProvider(baseline, expected)
    artifacts.corrupt_reads = tamper_export_after_plan
    service = WriteBackService(
        sessions=sessions,
        owner_subject="owner-a",
        provider_factory=lambda _session, _connection_id: provider,
        artifacts=artifacts,
    )
    try:
        yield sessions, service, provider, run_id, baseline, expected
    finally:
        await engine.dispose()


async def test_stale_revision_before_backup_is_conflict_with_zero_mutations() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.revision = "revision-human"
        provider.current = _canonical("45", neighbor="Human edit.\n")

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.CONFLICT
        assert result.conflict is not None
        assert result.verified_preview is None
        assert result.conflict.detection_stage == "BEFORE_BACKUP"
        assert provider.copy_calls == provider.commit_calls == 0


async def test_fresh_live_omitted_zero_section_break_passes_writeback_eligibility() -> None:
    async with _environment(
        old_token="30",
        new_token="35",
        fresh_live_snapshot=True,
    ) as (sessions, service, provider, run_id, baseline, expected):
        result = await service.execute(run_id)

        assert baseline["tabs"][0]["body"][0] == {
            "startIndex": None,
            "endIndex": 1,
            "type": "sectionBreak",
            "sectionStyle": {
                "sectionType": "CONTINUOUS",
                "contentDirection": "LEFT_TO_RIGHT",
                "columnSeparatorStyle": "NONE",
            },
        }
        assert expected["tabs"][0]["body"][0]["startIndex"] is None
        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert result.verified_preview is not None
        assert result.verified_preview.revision_id == "revision-B"
        preview_text = [block.text for block in result.verified_preview.blocks]
        assert preview_text == [
            "Vendor Agreement",
            "Payment Terms",
            "Payment is due within 35 days.",
            "Support",
        ]
        assert provider.copy_calls == provider.commit_calls == 1
        async with sessions() as session:
            plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run_id))
            proof = await session.scalar(
                select(MappingProof).where(MappingProof.sync_run_id == run_id)
            )
            persisted_run = await session.get(SyncRun, run_id)
            assert persisted_run is not None
            summary = await get_write_back_summary(session, persisted_run)
        assert plan is not None
        assert proof is not None
        assert summary is not None
        assert summary.write_plan_id == plan.id
        assert summary.write_plan_sha256 == plan.integrity_sha256
        assert summary.preview is not None
        assert summary.preview.old_text == "0"
        assert summary.preview.new_text == "5"
        assert summary.preview.context is not None
        assert summary.preview.context.source_snapshot_id == plan.source_snapshot_id
        assert summary.preview.context.before.model_dump() == {
            "text": "Payment is due within 30 days.",
            "highlight_start": 23,
            "highlight_end": 24,
        }
        assert summary.preview.context.after.model_dump() == {
            "text": "Payment is due within 35 days.",
            "highlight_start": 23,
            "highlight_end": 24,
        }
        assert plan.source_snapshot_id == proof.source_snapshot_id
        assert plan.mapping_proof_id == proof.id
        assert proof.proof_payload["location"] == {
            "tab_id": "t.0",
            "segment_id": "",
            "structural_element_index": 5,
            "paragraph_start_index": 34,
            "paragraph_end_index": 65,
            "text_run_index": 0,
            "text_run_start_index": 34,
            "text_run_end_index": 65,
            "edit_start_index": 57,
            "edit_end_index": 58,
        }
        assert plan.payload["expected_replacement"] == {
            "old_text": "0",
            "new_text": "5",
            "old_paragraph_sha256": proof.proof_payload["old_paragraph_sha256"],
            "new_paragraph_sha256": proof.proof_payload["new_paragraph_sha256"],
        }
        assert plan.provider_operations["operations"][0]["requests"] == [
            {
                "deleteContentRange": {
                    "range": {
                        "segmentId": "",
                        "tabId": "t.0",
                        "startIndex": 57,
                        "endIndex": 58,
                    }
                }
            },
            {
                "insertText": {
                    "location": {"segmentId": "", "tabId": "t.0", "index": 57},
                    "text": "5",
                }
            },
        ]


@pytest.mark.parametrize(
    ("start_index", "end_index", "element_type"),
    [
        (None, 2, "sectionBreak"),
        (None, 1, "paragraph"),
        ("0", 1, "sectionBreak"),
        ({}, 1, "sectionBreak"),
        (-1, 1, "sectionBreak"),
        (2, 1, "sectionBreak"),
    ],
)
def test_writeback_eligibility_does_not_generalize_omitted_provider_indexes(
    start_index: object,
    end_index: int,
    element_type: str,
) -> None:
    body = deepcopy(_fresh_live_canonical("30")["tabs"][0]["body"])
    body[0]["startIndex"] = start_index
    body[0]["endIndex"] = end_index
    body[0]["type"] = element_type

    with pytest.raises(
        WriteBackNotEligible,
        match=r"provider (startIndex|structural range) is malformed",
    ):
        _shift_body_indexes(
            body,
            replaced_start=57,
            replaced_end=58,
            delta=0,
        )


def test_writeback_eligibility_requires_persisted_null_zero_marker() -> None:
    body = deepcopy(_fresh_live_canonical("30")["tabs"][0]["body"])
    del body[0]["startIndex"]

    with pytest.raises(WriteBackNotEligible, match="provider startIndex is malformed"):
        _shift_body_indexes(
            body,
            replaced_start=57,
            replaced_end=58,
            delta=0,
        )


async def test_definitive_commit_preflight_failure_reuses_checkpoint_without_second_backup() -> (
    None
):
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.commit_error = GoogleIntegrationError(
            GoogleErrorCode.UNAVAILABLE,
            "preflight unavailable",
            retryable=True,
        )

        first = await service.execute(run_id)
        recovered = await service.execute(run_id)

        assert first.status is WriteBackStatus.ATTENTION
        assert first.attention_code == "GOOGLE_BATCH_UPDATE_PREFLIGHT_UNAVAILABLE"
        assert recovered.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == 1
        assert provider.commit_calls == 2


async def test_non_ready_or_inconsistent_plan_never_reaches_provider() -> None:
    async with _environment() as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            run = await session.get(SyncRun, run_id)
            assert run is not None
            run.state = SyncRunState.AWAITING_REVIEW
            await session.commit()

        with pytest.raises(WriteBackNotEligible):
            await service.execute(run_id)
        assert provider.events == []


async def test_reviewed_export_artifact_is_rehashed_again_before_external_effects() -> None:
    async with _environment(tamper_export_after_plan=True) as (
        _,
        service,
        provider,
        run_id,
        _,
        _,
    ):
        with pytest.raises(WriteBackNotEligible, match="immutable identity"):
            await service.execute(run_id)
        assert provider.events == []


async def test_watched_run_requires_exact_file_authorization_then_reuses_phase6() -> None:
    async with _environment(watched=True) as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            item = await session.scalar(
                select(WatchedItem).where(WatchedItem.last_enqueued_run_id == run_id)
            )
            assert link is not None and item is not None
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            item.current_in_scope = False
            await session.commit()

        with pytest.raises(WatchedFileOutOfScope):
            await service.execute(run_id)
        assert provider.events == []

        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            item = await session.scalar(
                select(WatchedItem).where(WatchedItem.last_enqueued_run_id == run_id)
            )
            assert link is not None and item is not None
            link.write_authorization_state = WriteAuthorizationState.REQUIRED
            item.current_in_scope = True
            await session.commit()

        with pytest.raises(ExactFileWriteAuthorizationRequired):
            await service.execute(run_id)
        assert provider.events == []
        assert provider.copy_calls == provider.commit_calls == 0

        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            assert link is not None
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            await session.commit()

        provider.is_app_authorized = False
        with pytest.raises(ExactFileWriteAuthorizationRequired):
            await service.execute(run_id)
        assert provider.events == ["read"]
        assert provider.copy_calls == provider.commit_calls == 0

        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            assert link is not None
            assert link.write_authorization_state is WriteAuthorizationState.REQUIRED
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            await session.commit()
        provider.is_app_authorized = True
        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert result.verified_preview is not None
        preview_text = [block.text for block in result.verified_preview.blocks]
        assert "Payment is due within 30 days." in preview_text
        assert "Trailing content stays exact." in preview_text
        assert provider.copy_calls == provider.commit_calls == 1


async def test_watched_root_path_is_rechecked_before_backup_and_after_write() -> None:
    async with _environment(watched=True) as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            assert link is not None
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            await session.commit()

        provider.watched_path_verified = False
        escaped_before_write = await service.execute(run_id)

        assert escaped_before_write.status is WriteBackStatus.FAILED
        assert escaped_before_write.attention_code == "WATCHED_FILE_OUT_OF_SCOPE"
        assert provider.copy_calls == provider.commit_calls == 0

    async with _environment(watched=True) as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            assert link is not None
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            await session.commit()
        provider.move_outside_before_commit = True

        escaped_at_commit = await service.execute(run_id)

        assert escaped_at_commit.status is WriteBackStatus.FAILED
        assert escaped_at_commit.attention_code == "WATCHED_FILE_OUT_OF_SCOPE"
        assert not escaped_at_commit.write_applied
        assert provider.copy_calls == provider.commit_calls == 1

    async with _environment(watched=True) as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id)
            )
            assert link is not None
            link.write_authorization_state = WriteAuthorizationState.AUTHORIZED
            await session.commit()
        provider.move_outside_after_commit = True

        escaped_after_write = await service.execute(run_id)

        assert escaped_after_write.status is WriteBackStatus.VERIFICATION_FAILED
        assert escaped_after_write.write_applied
        assert not escaped_after_write.structurally_verified
        assert provider.copy_calls == provider.commit_calls == 1


@pytest.mark.parametrize("tamper", ["mapping", "operation_mirror", "approval"])
async def test_immutable_plan_and_mapping_mirrors_are_revalidated_before_effects(
    tamper: str,
) -> None:
    async with _environment() as (sessions, service, provider, run_id, _, _):
        async with sessions() as session:
            if tamper == "mapping":
                proof = await session.scalar(
                    select(MappingProof).where(MappingProof.sync_run_id == run_id)
                )
                assert proof is not None
                proof.integrity_sha256 = "0" * 64
            elif tamper == "operation_mirror":
                plan = await session.scalar(
                    select(WritePlan).where(WritePlan.sync_run_id == run_id)
                )
                assert plan is not None
                plan.provider_operations = {"operations": []}
            else:
                decision = await session.scalar(
                    select(ReviewDecision).where(ReviewDecision.sync_run_id == run_id)
                )
                assert decision is not None
                decision.decision = ChangeDecision.REJECT
            await session.commit()

        with pytest.raises(WriteBackNotEligible):
            await service.execute(run_id)
        assert provider.events == []


@pytest.mark.parametrize("failure", ["canonical", "acl", "location"])
async def test_backup_must_be_content_and_permission_verified_before_write(
    failure: str,
) -> None:
    async with _environment() as (_, service, provider, run_id, baseline, _):
        update: dict[str, Any]
        if failure == "canonical":
            update = {
                "content_matches_baseline": False,
                "canonical_sha256": sha256_json(_canonical("99")),
            }
        elif failure == "acl":
            update = {"acl_not_broader": False}
        else:
            update = {"expected_location": False}
        provider.backup_verification = provider.backup_verification.model_copy(update=update)

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.FAILED
        assert result.attention_code == "GOOGLE_BACKUP_VERIFICATION_FAILED"
        assert provider.events[:3] == ["read", "copy", "verify-backup"]
        assert provider.commit_calls == 0
        assert (
            provider.backup_verification.canonical_sha256 != sha256_json(baseline)
            or (not provider.backup_verification.acl_not_broader)
            or not provider.backup_verification.expected_location
        )


async def test_backup_unknown_is_never_retried_and_never_writes() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.copy_unknown = True

        first = await service.execute(run_id)
        second = await service.execute(run_id)

        assert first.status is second.status is WriteBackStatus.ATTENTION
        assert first.attention_code == "GOOGLE_BACKUP_COPY_OUTCOME_UNKNOWN"
        assert provider.copy_calls == 1
        assert provider.commit_calls == 0


async def test_backup_verification_read_can_resume_without_a_second_copy() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.verify_error = GoogleIntegrationError(
            GoogleErrorCode.UNAVAILABLE,
            "Google API unavailable",
            retryable=True,
        )

        stopped = await service.execute(run_id)
        assert stopped.status is WriteBackStatus.ATTENTION
        assert stopped.attention_code == "GOOGLE_BACKUP_VERIFICATION_UNAVAILABLE"
        assert stopped.backup_created
        assert provider.copy_calls == 1
        assert provider.commit_calls == 0

        provider.verify_error = None
        resumed = await service.execute(run_id)
        assert resumed.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == 1
        assert provider.verify_calls == 2
        assert provider.commit_calls == 1


async def test_human_change_after_backup_is_conflict_without_batch_update() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.change_after_backup = True

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.CONFLICT
        assert result.conflict is not None
        assert result.conflict.detection_stage == "AFTER_BACKUP"
        assert result.backup_verified
        assert provider.copy_calls == 1
        assert provider.commit_calls == 0


async def test_exact_persisted_plan_is_sent_once_with_required_revision() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.WRITE_VERIFIED
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
        assert operation.provider_payload() == {
            "requests": [
                {
                    "deleteContentRange": {
                        "range": {
                            "segmentId": "",
                            "tabId": "t.0",
                            "startIndex": 184,
                            "endIndex": 186,
                        }
                    }
                },
                {
                    "insertText": {
                        "location": {
                            "segmentId": "",
                            "tabId": "t.0",
                            "index": 184,
                        },
                        "text": "30",
                    }
                },
            ],
            "writeControl": {"requiredRevisionId": "revision-A"},
        }


async def test_phase6_verifies_longer_replacement_with_unchanged_backup_and_guard() -> None:
    async with _environment(old_token="30", new_token="14 calendar") as (
        _,
        service,
        provider,
        run_id,
        baseline,
        expected,
    ):
        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == provider.commit_calls == 1
        operation = provider.operations[0]
        assert operation.required_revision_id == "revision-A"
        assert operation.requests[0]["deleteContentRange"]["range"] == {
            "segmentId": "",
            "tabId": "t.0",
            "startIndex": 184,
            "endIndex": 186,
        }
        assert operation.requests[1]["insertText"] == {
            "location": {"segmentId": "", "tabId": "t.0", "index": 184},
            "text": "14 calendar",
        }
        assert baseline["tabs"][0]["body"][1]["endIndex"] == 193
        assert expected["tabs"][0]["body"][1]["endIndex"] == 202
        assert baseline["tabs"][0]["body"][2]["startIndex"] == 220
        assert expected["tabs"][0]["body"][2]["startIndex"] == 229
        assert (
            expected["tabs"][0]["body"][2]["runs"][0]["text"] == "Trailing content stays exact.\n"
        )


async def test_provider_revision_rejection_is_durable_conflict_without_force() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.commit_result = GuardedCommitResult(
            classification=CommitClassification.CONFLICT,
            safe_provider_evidence={"reason": "required_revision_mismatch"},
        )

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.CONFLICT
        assert result.conflict is not None
        assert result.conflict.detection_stage == "ATOMIC_GUARD"
        assert provider.commit_calls == 1
        assert "overwrite" not in result.model_dump_json().lower()


@pytest.mark.parametrize(
    ("postimage", "revision", "expected_status", "expected_code"),
    [
        ("expected", "revision-B", WriteBackStatus.WRITE_VERIFIED, None),
        (
            "baseline",
            "revision-A",
            WriteBackStatus.ATTENTION,
            "GOOGLE_BATCH_UPDATE_NOT_VISIBLY_APPLIED",
        ),
        (
            "unexpected",
            "revision-human",
            WriteBackStatus.CONFLICT,
            "GOOGLE_SOURCE_REVISION_CONFLICT",
        ),
    ],
)
async def test_unknown_write_reconciles_by_complete_canonical_state_without_retry(
    postimage: str,
    revision: str,
    expected_status: WriteBackStatus,
    expected_code: str | None,
) -> None:
    async with _environment() as (_, service, provider, run_id, baseline, expected):
        provider.commit_unknown = True
        provider.unknown_revision = revision
        provider.unknown_postimage = {
            "expected": expected,
            "baseline": baseline,
            "unexpected": _canonical("30", neighbor="Unexpected change.\n"),
        }[postimage]

        first = await service.execute(run_id)
        second = await service.execute(run_id)

        assert first.status is expected_status
        assert second.status is expected_status
        assert first.attention_code == expected_code
        assert provider.commit_calls == 1


async def test_unrelated_post_write_change_fails_structural_verification() -> None:
    async with _environment(old_token="30", new_token="14 calendar") as (
        _,
        service,
        provider,
        run_id,
        _,
        _,
    ):
        provider.expected = _canonical("14 calendar", neighbor="Unrelated changed.\n")

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.VERIFICATION_FAILED
        assert not result.structurally_verified
        assert result.attention_code == "GOOGLE_POSTIMAGE_VERIFICATION_FAILED"


async def test_repeated_execute_after_verified_success_has_no_new_effects() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        first = await service.execute(run_id)
        second = await service.execute(run_id)

        assert first.status is second.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == provider.commit_calls == 1


async def test_restart_after_verified_backup_reuses_it_without_second_copy() -> None:
    async with _environment() as (sessions, service, provider, run_id, baseline, _):
        await _seed_verified_backup(sessions, run_id, sha256_json(baseline))

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == 0
        assert provider.commit_calls == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Backup)) == 1


async def test_restart_after_started_write_reconciles_without_second_write() -> None:
    async with _environment() as (sessions, service, provider, run_id, _, expected):
        await _seed_verified_backup(sessions, run_id, sha256_json(_canonical("45")))
        await _seed_started_write(sessions, run_id)
        provider.current = expected
        provider.revision = "revision-B"

        result = await service.execute(run_id)

        assert result.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.commit_calls == 0


async def test_two_concurrent_execute_calls_claim_only_one_external_workflow() -> None:
    async with _environment() as (_, service, provider, run_id, _, _):
        provider.block_copy = asyncio.Event()
        first_task = asyncio.create_task(service.execute(run_id))
        await provider.copy_entered.wait()

        second = await service.execute(run_id)
        provider.block_copy.set()
        first = await first_task

        assert second.status is WriteBackStatus.IN_PROGRESS
        assert first.status is WriteBackStatus.WRITE_VERIFIED
        assert provider.copy_calls == provider.commit_calls == 1


@pytest.mark.parametrize("choice", [ConflictChoice.CANCEL, ConflictChoice.REVIEW_LATEST])
async def test_conflict_decisions_are_explicit_and_never_execute_stale_plan(
    choice: ConflictChoice,
) -> None:
    async with _environment() as (sessions, service, provider, run_id, _, _):
        provider.revision = "revision-human"
        provider.current = _canonical("45", neighbor="Human edit.\n")
        conflict = await service.execute(run_id)
        assert conflict.status is WriteBackStatus.CONFLICT

        decided = await service.decide_conflict(run_id, choice)

        expected = (
            WriteBackStatus.CANCELLED
            if choice is ConflictChoice.CANCEL
            else WriteBackStatus.REVIEW_LATEST
        )
        assert decided.status is expected
        assert provider.copy_calls == provider.commit_calls == 0
        async with sessions() as session:
            row = await session.scalar(
                select(WriteConflict).where(WriteConflict.sync_run_id == run_id)
            )
            assert row is not None and row.decision is choice
            assert await session.scalar(select(func.count()).select_from(VerificationResult)) == 0


async def test_execution_evidence_and_response_do_not_expose_secrets_or_raw_bodies() -> None:
    async with _environment() as (sessions, service, _provider, run_id, _, _):
        result = await service.execute(run_id)
        serialized = result.model_dump_json().lower()
        for forbidden in (
            "authorization",
            "access_token",
            "refresh_token",
            "superdocs_api_key",
        ):
            assert forbidden not in serialized

        async with sessions() as session:
            effects = tuple(await session.scalars(select(ExternalEffect)))
            assert {effect.effect_type for effect in effects} == {
                EffectType.GOOGLE_BACKUP_COPY,
                EffectType.GOOGLE_BATCH_UPDATE,
            }
            assert all("Authorization" not in str(effect.request_metadata) for effect in effects)
            assert all(effect.outcome is EffectOutcome.SUCCEEDED for effect in effects)
            for effect in effects:
                evidence = (
                    f"{effect.request_metadata}{effect.reconciliation_evidence}"
                    f"{effect.last_error}"
                ).lower()
                assert "payment is due" not in evidence
            backup = await session.scalar(select(Backup))
            assert backup is not None and backup.status is BackupStatus.VERIFIED


async def _seed_verified_backup(
    sessions: async_sessionmaker[Any], run_id: Any, canonical_sha256: str
) -> None:
    async with sessions() as session:
        plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run_id))
        run = await session.get(SyncRun, run_id)
        assert plan is not None and run is not None
        effect = ExternalEffect(
            sync_run_id=run_id,
            effect_key=f"google-backup:{plan.id}",
            effect_type=EffectType.GOOGLE_BACKUP_COPY,
            outcome=EffectOutcome.SUCCEEDED,
            request_fingerprint="b" * 64,
            request_metadata={"write_plan_sha256": plan.integrity_sha256},
            provider_external_id="backup-file-1",
            attempt_count=1,
            started_at=datetime.now(UTC),
            resolved_at=datetime.now(UTC),
        )
        session.add(effect)
        await session.flush()
        session.add(
            Backup(
                sync_run_id=run_id,
                write_plan_id=plan.id,
                external_effect_id=effect.id,
                status=BackupStatus.VERIFIED,
                provider_backup_file_id="backup-file-1",
                baseline_revision_id="revision-A",
                canonical_sha256=canonical_sha256,
                location_evidence={"expected_parent": "parent-a"},
                acl_evidence={"acl_not_broader": True},
                verified_at=datetime.now(UTC),
            )
        )
        run.state = SyncRunState.COMMITTING
        await session.commit()


async def _seed_started_write(sessions: async_sessionmaker[Any], run_id: Any) -> None:
    async with sessions() as session:
        plan = await session.scalar(select(WritePlan).where(WritePlan.sync_run_id == run_id))
        assert plan is not None
        session.add(
            ExternalEffect(
                sync_run_id=run_id,
                effect_key=f"google-batch-update:{plan.id}",
                effect_type=EffectType.GOOGLE_BATCH_UPDATE,
                outcome=EffectOutcome.STARTED,
                request_fingerprint=plan.integrity_sha256,
                request_metadata={"write_plan_sha256": plan.integrity_sha256},
                attempt_count=1,
                started_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await session.commit()
