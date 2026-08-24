import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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

from docrelay.api.watch import _rule_response
from docrelay.domain.enums import (
    ConnectionStatus,
    EffectType,
    Provider,
    SyncRunState,
    WatchItemOutcome,
    WatchScanStatus,
    WriteAuthorizationState,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import GOOGLE_WATCH_SCOPES
from docrelay.integrations.google.read_only import (
    DRIVE_FOLDER_MIME,
    GOOGLE_DOC_MIME,
    BaselineCaptureResult,
    GoogleBaselineCaptureService,
    GoogleDrivePage,
    GoogleFileMetadata,
    GoogleReadCapabilities,
    NativeGoogleDocument,
)
from docrelay.integrations.google.services import RegisteredBaseline
from docrelay.integrations.superdocs.contracts import (
    IngestedDocument,
    JobReference,
    JobSnapshot,
    PendingChange,
    SessionDocument,
    SessionDocumentIdentity,
)
from docrelay.persistence.base import Base
from docrelay.persistence.models import (
    Backup,
    CloudConnection,
    CloudDocument,
    ExternalEffect,
    GoogleBaselineCapture,
    SyncRun,
    WatchedItem,
    WatchRunLink,
    WatchScan,
    WatchScanItem,
)
from docrelay.services.artifacts import InMemoryArtifactStore
from docrelay.services.machine import (
    MachineWriteBackStatus,
    MultiDocumentQueryService,
    ReviewStatus,
)
from docrelay.services.superdocs_workflow import SuperDocsWorkflow
from docrelay.services.watch import WatchClaimLost, WatchInvalidRoot, WatchService


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _folder(
    file_id: str, *, parent: str | None = None, drive_id: str | None = None
) -> GoogleFileMetadata:
    return GoogleFileMetadata(
        file_id=file_id,
        name=f"Folder {file_id}",
        mime_type=DRIVE_FOLDER_MIME,
        parent_ids=(parent,) if parent else (),
        drive_id=drive_id,
        provider_version="1",
        modified_time=datetime(2026, 8, 12, tzinfo=UTC),
        spaces=("drive",),
        owned_by_me=True,
        capabilities=GoogleReadCapabilities(),
    )


def _document_metadata(
    file_id: str,
    *,
    parent: str,
    version: str = "1",
    app_authorized: bool = False,
) -> GoogleFileMetadata:
    return GoogleFileMetadata(
        file_id=file_id,
        name=f"Document {file_id}",
        mime_type=GOOGLE_DOC_MIME,
        parent_ids=(parent,),
        provider_version=version,
        modified_time=datetime(2026, 8, 12, int(version), tzinfo=UTC),
        spaces=("drive",),
        is_app_authorized=app_authorized,
        capabilities=GoogleReadCapabilities(
            can_edit=True,
            can_modify_content=True,
            can_download=True,
            can_copy=True,
        ),
    )


def _native_payload(file_id: str, revision: str) -> dict[str, Any]:
    return {
        "documentId": file_id,
        "revisionId": revision,
        "tabs": [
            {
                "tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
                "documentTab": {
                    "body": {
                        "content": [
                            {
                                "startIndex": 1,
                                "endIndex": 37,
                                "paragraph": {
                                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                    "elements": [
                                        {
                                            "startIndex": 1,
                                            "endIndex": 37,
                                            "textRun": {
                                                "content": "Payment is due within 45 days.\n"
                                            },
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                },
            }
        ],
    }


class FakeDrive:
    def __init__(self, *, page_size: int = 1) -> None:
        self.files: dict[str, GoogleFileMetadata] = {}
        self.children: dict[str, list[str]] = {}
        self.page_size = page_size
        self.listed_folders: list[str] = []
        self.move_when_listed: dict[str, tuple[str, str]] = {}
        self.move_when_read: dict[str, str] = {}
        self.native_read_count = 0
        self.export_count = 0

    def add(self, metadata: GoogleFileMetadata) -> None:
        self.files[metadata.file_id] = metadata
        if metadata.parent_ids:
            self.children.setdefault(metadata.parent_ids[0], []).append(metadata.file_id)

    def move_version(
        self,
        file_id: str,
        *,
        version: str,
        parent: str | None = None,
        app_authorized: bool | None = None,
    ) -> None:
        current = self.files[file_id]
        update: dict[str, object] = {
            "provider_version": version,
            "modified_time": datetime(2026, 8, 12, int(version), tzinfo=UTC),
        }
        if parent is not None:
            update["parent_ids"] = (parent,)
        if app_authorized is not None:
            update["is_app_authorized"] = app_authorized
        self.files[file_id] = current.model_copy(update=update)

    async def get_file(self, file_id: str) -> GoogleFileMetadata:
        new_parent = self.move_when_read.pop(file_id, None)
        if new_parent is not None:
            self.files[file_id] = self.files[file_id].model_copy(
                update={"parent_ids": (new_parent,)}
            )
        return self.files[file_id]

    async def list_children(
        self, folder_id: str, *, page_token: str | None = None
    ) -> GoogleDrivePage:
        self.listed_folders.append(folder_id)
        move = self.move_when_listed.pop(folder_id, None)
        if move is not None:
            file_id, new_parent = move
            self.files[file_id] = self.files[file_id].model_copy(
                update={"parent_ids": (new_parent,)}
            )
        values = self.children.get(folder_id, [])
        start = int(page_token or 0)
        stop = start + self.page_size
        token = str(stop) if stop < len(values) else None
        return GoogleDrivePage(
            items=tuple(self.files[file_id] for file_id in values[start:stop]),
            next_page_token=token,
        )

    async def get_document(self, file_id: str) -> NativeGoogleDocument:
        self.native_read_count += 1
        version = self.files[file_id].provider_version
        assert version is not None
        revision = f"revision-{version}"
        return NativeGoogleDocument(
            file_id=file_id,
            revision_id=revision,
            raw_payload=_native_payload(file_id, revision),
        )

    async def export_docx(self, file_id: str) -> bytes:
        self.export_count += 1
        version = self.files[file_id].provider_version
        return f"PK\x03\x04 {file_id} version {version} with 45 days".encode()


class FakeGoogleOperations:
    def __init__(
        self,
        *,
        session: AsyncSession,
        drive: FakeDrive,
        watch_authorized: bool,
    ) -> None:
        self.session = session
        self.drive = drive
        self.watch_authorized = watch_authorized

    async def watch_read_client(self, connection_id: UUID) -> FakeDrive:
        del connection_id
        self._require_scope()
        return self.drive

    async def require_watch_authorization(self, connection_id: UUID) -> None:
        del connection_id
        self._require_scope()

    async def register_and_capture(
        self,
        *,
        connection_id: UUID,
        file_id: str,
        required_scopes: tuple[str, ...],
    ) -> RegisteredBaseline:
        assert required_scopes == GOOGLE_WATCH_SCOPES
        self._require_scope()
        result: BaselineCaptureResult = await GoogleBaselineCaptureService(
            self.drive, max_attempts=2
        ).capture(connection_id=connection_id, file_id=file_id)
        document = await self.session.scalar(
            select(CloudDocument).where(
                CloudDocument.connection_id == connection_id,
                CloudDocument.provider_file_id == file_id,
            )
        )
        if document is None:
            document = CloudDocument(
                connection_id=connection_id,
                provider_file_id=file_id,
                mime_type=result.metadata.mime_type,
            )
            self.session.add(document)
            await self.session.flush()
        document.display_name = result.metadata.name
        document.parent_ids = list(result.metadata.parent_ids)
        document.drive_id = result.metadata.drive_id
        document.last_seen_revision_id = result.revision_id
        document.last_seen_at = result.captured_at
        document.provider_metadata = {
            "is_app_authorized": result.metadata.is_app_authorized,
            "provider_version": result.metadata.provider_version,
        }
        capture = GoogleBaselineCapture(
            cloud_document_id=document.id,
            provider_revision_id=result.revision_id,
            native_raw_sha256=result.native_raw_sha256,
            native_canonical_sha256=result.native_canonical_sha256,
            exported_docx_sha256=result.exported_docx_sha256,
            exported_docx_size_bytes=result.exported_docx_size_bytes,
            canonicalizer_version=result.canonicalizer_version,
            canonical_payload=result.canonical_payload,
            capability_evidence=result.metadata.capabilities.model_dump(mode="json"),
            parent_ids=list(result.metadata.parent_ids),
            attempt_count=result.attempt_count,
            capture_started_at=result.capture_started_at,
            captured_at=result.captured_at,
            provider_evidence={
                "revision_before": result.revision_id,
                "revision_after": result.revision_id,
                "watch_readonly": True,
            },
        )
        self.session.add(capture)
        await self.session.commit()
        return RegisteredBaseline(document=document, capture=capture, result=result)

    async def verify_exact_file_write_authorization(
        self, *, connection_id: UUID, file_id: str
    ) -> GoogleFileMetadata:
        del connection_id
        self._require_scope()
        return await self.drive.get_file(file_id)

    def _require_scope(self) -> None:
        if not self.watch_authorized:
            raise GoogleIntegrationError(
                GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED,
                "watch scope required",
            )


class FakeSuperDocs:
    def __init__(self) -> None:
        self.upload_calls = 0
        self.start_calls = 0
        self.instructions: list[str] = []
        self.sessions: set[str] = set()

    async def upload_docx(
        self, *, docx_bytes: bytes, filename: str, session_id: str, open_mode: str
    ) -> IngestedDocument:
        assert docx_bytes and filename and open_mode == "replace"
        self.upload_calls += 1
        self.sessions.add(session_id)
        return IngestedDocument(
            identity=SessionDocumentIdentity(
                session_id=session_id,
                session_document_id="doc_primary",
            ),
            upload_version_id=f"upload-{self.upload_calls}",
            baseline_html_sha256=_sha(b"<p>45 days</p>"),
            chunks_count=1,
            safe_evidence={"fresh_ingestion": True},
        )

    async def list_session_documents(
        self, session_id: str, *, include_html: bool = False
    ) -> tuple[SessionDocument, ...]:
        del include_html
        return (
            SessionDocument(
                identity=SessionDocumentIdentity(
                    session_id=session_id,
                    session_document_id="doc_primary",
                    durable_document_id=f"durable-{session_id}",
                ),
                title="source.docx",
                focused=True,
                chunks_count=1,
                version_id="upload-version",
                safe_evidence={},
            ),
        )

    async def start_edit(
        self,
        *,
        target: SessionDocumentIdentity,
        instruction: str,
        approval_mode: str,
        model_tier: str | None,
        thinking_depth: str | None,
    ) -> JobReference:
        del model_tier, thinking_depth
        assert approval_mode == "ask_every_time"
        self.start_calls += 1
        self.instructions.append(instruction)
        return JobReference(
            job_id=f"job-{target.session_id}",
            session_id=target.session_id,
            status="in_progress",
        )

    async def recover_session_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]:
        del session_id
        return ()

    async def get_job(self, job_id: str) -> JobSnapshot:
        session_id = job_id.removeprefix("job-")
        return JobSnapshot(
            reference=JobReference(
                job_id=job_id,
                session_id=session_id,
                status="awaiting_approval",
            ),
            awaiting_kind="change_review",
            pending_changes=(
                PendingChange(
                    change_id="change-1",
                    operation="edit",
                    document_id="doc_primary",
                    chunk_id="chunk-1",
                    old_html="<p>45 days</p>",
                    new_html="<p>30 days</p>",
                    ai_explanation="Requested change",
                    safe_evidence={},
                ),
            ),
            progress=50,
            safe_metadata={},
        )


class WatchHarness:
    def __init__(
        self,
        *,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
        connection_id: UUID,
        drive: FakeDrive,
        superdocs: FakeSuperDocs,
        orchestrator: SuperDocsWorkflow,
    ) -> None:
        self.engine = engine
        self.sessions = sessions
        self.connection_id = connection_id
        self.drive = drive
        self.superdocs = superdocs
        self.orchestrator = orchestrator
        self.watch_authorized = True
        self.service = self.new_service()

    def new_service(self) -> WatchService:
        return WatchService(
            sessions=self.sessions,
            owner_subject="owner-watch",
            google_factory=lambda session: FakeGoogleOperations(
                session=session,
                drive=self.drive,
                watch_authorized=self.watch_authorized,
            ),
            runs=self.orchestrator,
            scan_lease_seconds=60,
            max_items_per_scan=100,
        )


@asynccontextmanager
async def _environment() -> AsyncIterator[WatchHarness]:
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
            owner_subject="owner-watch",
            provider=Provider.GOOGLE,
            provider_account_subject="principal-watch",
            status=ConnectionStatus.CONNECTED,
            granted_scopes={"scopes": list(GOOGLE_WATCH_SCOPES)},
        )
        session.add(connection)
        await session.commit()
        connection_id = connection.id
    drive = FakeDrive(page_size=1)
    superdocs = FakeSuperDocs()
    orchestrator = SuperDocsWorkflow(
        sessions=sessions,
        superdocs=superdocs,  # type: ignore[arg-type]
        artifacts=InMemoryArtifactStore(),
        owner_subject="owner-watch",
    )
    harness = WatchHarness(
        engine=engine,
        sessions=sessions,
        connection_id=connection_id,
        drive=drive,
        superdocs=superdocs,
        orchestrator=orchestrator,
    )
    try:
        yield harness
    finally:
        await engine.dispose()


async def _configured_tree(harness: WatchHarness, *, include_document: bool = True) -> UUID:
    harness.drive.add(_folder("root"))
    harness.drive.add(_folder("finance", parent="root"))
    harness.drive.add(_folder("nested", parent="finance"))
    harness.drive.add(_folder("outside"))
    if include_document:
        harness.drive.add(_document_metadata("contract", parent="nested"))
        harness.drive.add(_document_metadata("outside-doc", parent="outside"))
    watch = await harness.service.configure_root(
        connection_id=harness.connection_id,
        root_folder_id="root",
        interval_seconds=60,
        enabled=True,
    )
    return watch.id


async def test_recursive_paginated_scan_stays_in_root_reuses_phase3_and_dedupes() -> None:
    async with _environment() as harness:
        watch_id = await _configured_tree(harness)
        await harness.service.configure_rule(
            watch_id,
            folder_id="root",
            instruction="Root fallback instruction.",
            enabled=True,
        )
        finance_rule = await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction='Replace "45 days" with "30 days".',
            enabled=True,
        )
        assert _rule_response(finance_rule).folder_name == "Folder finance"

        first = await harness.service.trigger_manual(watch_id)

        assert first.status is WatchScanStatus.SUCCEEDED
        assert first.discovered_count == 1
        assert first.enqueued_count == 1
        assert set(harness.drive.listed_folders) == {"root", "finance", "nested"}
        assert "outside" not in harness.drive.listed_folders
        async with harness.sessions() as session:
            run = await session.scalar(select(SyncRun))
            link = await session.scalar(select(WatchRunLink))
            google_effect_count = await session.scalar(
                select(func.count())
                .select_from(ExternalEffect)
                .where(
                    ExternalEffect.effect_type.in_(
                        (EffectType.GOOGLE_BACKUP_COPY, EffectType.GOOGLE_BATCH_UPDATE)
                    )
                )
            )
            assert run is not None
            assert run.folder_rule_id == finance_rule.id
            assert run.rule_snapshot["matched_folder_id"] == "finance"
            assert run.rule_snapshot["instruction"] == finance_rule.instruction
            assert run.state is SyncRunState.EDITING
            assert link is not None
            assert link.write_authorization_state is WriteAuthorizationState.REQUIRED
            assert google_effect_count == 0
            assert await session.scalar(select(func.count()).select_from(Backup)) == 0

        review = await harness.orchestrator.resume(run.id)
        assert review.state is SyncRunState.AWAITING_REVIEW
        assert review.write_authorization is WriteAuthorizationState.REQUIRED

        second = await harness.service.trigger_manual(watch_id)
        assert second.unchanged_count == 1
        assert second.enqueued_count == 0
        assert harness.superdocs.upload_calls == harness.superdocs.start_calls == 1
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 1

        still_required = await harness.service.verify_run_write_authorization(
            run.id, picker_file_id="contract"
        )
        assert still_required.write_authorization_state is WriteAuthorizationState.REQUIRED
        harness.drive.move_version("contract", version="1", app_authorized=True)
        authorized = await harness.service.verify_run_write_authorization(
            run.id, picker_file_id="contract"
        )
        assert authorized.write_authorization_state is WriteAuthorizationState.AUTHORIZED
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 1

        harness.drive.children["nested"].remove("contract")
        moved = await harness.service.trigger_manual(watch_id)
        assert moved.skipped_count == 1
        async with harness.sessions() as session:
            watched = await session.scalar(
                select(WatchedItem).where(WatchedItem.provider_file_id == "contract")
            )
            assert watched is not None and not watched.current_in_scope
            observation = await session.scalar(
                select(WatchScanItem).where(
                    WatchScanItem.watch_scan_id == moved.id,
                    WatchScanItem.provider_file_id == "contract",
                )
            )
            assert observation is not None
            assert observation.outcome is WatchItemOutcome.OUT_OF_SCOPE


async def test_scan_machine_view_groups_only_created_runs_and_keeps_siblings_independent() -> None:
    async with _environment() as harness:
        watch_id = await _configured_tree(harness)
        harness.drive.add(_document_metadata("policy", parent="finance"))
        rule = await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction='Replace "45 days" with "30 days".',
            enabled=True,
        )
        first = await harness.service.trigger_manual(watch_id)
        queries = MultiDocumentQueryService(sessions=harness.sessions, owner_subject="owner-watch")

        first_view = await queries.get_scan(first.id)
        repeated_read = await queries.get_scan(first.id)
        all_runs = await queries.list_runs()

        assert first_view == repeated_read
        assert {row.provider_file_id for row in first_view.items} == {"contract", "policy"}
        assert len(first_view.runs) == 2
        assert {row.run_id for row in all_runs} == {row.run_id for row in first_view.runs}
        assert all(row.run_created_in_scan for row in first_view.items)
        assert all(row.matched_rule_id == rule.id for row in first_view.items)
        assert all(row.matched_rule_version == rule.version for row in first_view.items)
        assert all(row.review_status is ReviewStatus.NOT_READY for row in first_view.runs)
        assert all(
            row.write_authorization_status is WriteAuthorizationState.REQUIRED
            for row in first_view.runs
        )
        assert all(
            row.write_back_status is MachineWriteBackStatus.NOT_READY for row in first_view.runs
        )

        conflicted_id = first_view.runs[0].run_id
        sibling_id = first_view.runs[1].run_id
        async with harness.sessions() as session:
            conflicted = await session.get(SyncRun, conflicted_id)
            sibling = await session.get(SyncRun, sibling_id)
            assert conflicted is not None and sibling is not None
            conflicted.state = SyncRunState.CONFLICT
            conflicted.failure_code = "GOOGLE_SOURCE_REVISION_CONFLICT"
            await session.commit()

        independent = await queries.list_watch_runs(watch_id)
        by_id = {row.run_id: row for row in independent}
        assert by_id[conflicted_id].workflow_state is SyncRunState.CONFLICT
        assert by_id[conflicted_id].last_error_code == "GOOGLE_SOURCE_REVISION_CONFLICT"
        assert by_id[sibling_id].workflow_state is SyncRunState.EDITING
        assert by_id[sibling_id].last_error_code is None

        second = await harness.service.trigger_manual(watch_id)
        second_view = await queries.get_scan(second.id)
        assert second_view.runs == ()
        assert all(row.outcome is WatchItemOutcome.UNCHANGED for row in second_view.items)
        assert all(row.run_id is not None for row in second_view.items)
        assert not any(row.run_created_in_scan for row in second_view.items)
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 2


async def test_missing_rule_is_explicit_and_changed_versions_get_one_frozen_rule_each() -> None:
    async with _environment() as harness:
        watch_id = await _configured_tree(harness)
        no_rule = await harness.service.trigger_manual(watch_id)
        assert no_rule.enqueued_count == 0
        assert no_rule.skipped_count == 1
        items = await harness.service.list_scan_items(no_rule.id)
        assert items[0].outcome is WatchItemOutcome.NO_RULE
        assert items[0].reason_code == "NO_APPLICABLE_RULE"

        rule_v1 = await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction="Instruction version one.",
            enabled=True,
        )
        first_enqueued = await harness.service.trigger_manual(watch_id)
        assert first_enqueued.enqueued_count == 1

        rule_v2 = await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction="Instruction version two.",
            enabled=True,
        )
        harness.drive.move_version("contract", version="2")
        changed = await harness.service.trigger_manual(watch_id)
        assert changed.changed_count == 1
        assert changed.enqueued_count == 1

        await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction="Instruction version three.",
            enabled=True,
        )
        async with harness.sessions() as session:
            runs = (
                await session.scalars(select(SyncRun).order_by(SyncRun.created_at, SyncRun.id))
            ).all()
            assert len(runs) == 2
            by_revision = {run.baseline_revision_id: run for run in runs}
            first_run = by_revision["revision-1"]
            second_run = by_revision["revision-2"]
            assert first_run.folder_rule_id == rule_v1.id
            assert first_run.rule_snapshot["instruction"] == "Instruction version one."
            assert second_run.folder_rule_id == rule_v2.id
            assert second_run.folder_rule_version == 2
            assert second_run.rule_snapshot["instruction"] == "Instruction version two."

        repeated = await harness.service.trigger_manual(watch_id)
        assert repeated.enqueued_count == 0
        summaries = await MultiDocumentQueryService(
            sessions=harness.sessions, owner_subject="owner-watch"
        ).list_watch_runs(watch_id)
        assert {row.provider_version for row in summaries} == {"1", "2"}
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 2


async def test_due_claim_is_single_logical_scan_and_expired_lease_reenters_same_scan() -> None:
    async with _environment() as harness:
        await _configured_tree(harness, include_document=False)
        first_claims = await harness.service.claim_due()
        duplicate_claims = await harness.service.claim_due()
        assert len(first_claims) == 1
        assert duplicate_claims == ()
        first = first_claims[0]

        async with harness.sessions() as session:
            scan = await session.get(WatchScan, first.scan_id)
            assert scan is not None
            scan.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        restarted = harness.new_service()
        reclaimed = await restarted.claim_due()
        assert len(reclaimed) == 1
        assert reclaimed[0].scan_id == first.scan_id
        assert reclaimed[0].lease_token != first.lease_token

        with pytest.raises(WatchClaimLost):
            await harness.service.execute_claim(first)
        completed = await restarted.execute_claim(reclaimed[0])
        assert completed.status is WatchScanStatus.SUCCEEDED
        assert completed.claim_generation == 2
        async with harness.sessions() as session:
            scans = await session.scalar(select(func.count()).select_from(WatchScan))
            assert scans == 1


async def test_watch_refuses_insufficient_scope_and_shared_drive_root() -> None:
    async with _environment() as harness:
        harness.drive.add(_folder("root"))
        harness.watch_authorized = False
        harness.service = harness.new_service()
        with pytest.raises(GoogleIntegrationError) as scope_error:
            await harness.service.configure_root(
                connection_id=harness.connection_id,
                root_folder_id="root",
                interval_seconds=60,
                enabled=False,
            )
        assert scope_error.value.code is GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED

        harness.watch_authorized = True
        harness.service = harness.new_service()
        harness.drive.add(_folder("shared-root", drive_id="shared-drive-id"))
        with pytest.raises(WatchInvalidRoot):
            await harness.service.configure_root(
                connection_id=harness.connection_id,
                root_folder_id="shared-root",
                interval_seconds=60,
                enabled=False,
            )

        shared_with_me = _folder("shared-with-me")
        harness.drive.add(shared_with_me.model_copy(update={"owned_by_me": False}))
        with pytest.raises(WatchInvalidRoot):
            await harness.service.configure_root(
                connection_id=harness.connection_id,
                root_folder_id="shared-with-me",
                interval_seconds=60,
                enabled=False,
            )


async def test_folder_move_during_scan_discards_page_and_creates_no_run() -> None:
    async with _environment() as harness:
        watch_id = await _configured_tree(harness)
        await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction="Should never run after folder escape.",
            enabled=True,
        )
        harness.drive.move_when_listed["finance"] = ("finance", "outside")

        scan = await harness.service.trigger_manual(watch_id)

        assert scan.status is WatchScanStatus.FAILED
        assert scan.failure_code == "WATCH_DISCOVERY_FAILED"
        assert "outside" not in harness.drive.listed_folders
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 0


async def test_document_move_before_capture_is_not_read_or_enqueued() -> None:
    async with _environment() as harness:
        watch_id = await _configured_tree(harness)
        await harness.service.configure_rule(
            watch_id,
            folder_id="finance",
            instruction="Should never read after document escape.",
            enabled=True,
        )
        harness.drive.move_when_read["contract"] = "outside"

        scan = await harness.service.trigger_manual(watch_id)

        assert scan.status is WatchScanStatus.SUCCEEDED
        assert scan.skipped_count == 1
        assert scan.failed_count == 0
        assert harness.drive.native_read_count == 0
        assert harness.drive.export_count == 0
        async with harness.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SyncRun)) == 0
            assert await session.scalar(select(func.count()).select_from(CloudDocument)) == 0
