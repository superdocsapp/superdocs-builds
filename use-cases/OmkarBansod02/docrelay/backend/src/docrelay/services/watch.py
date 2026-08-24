import hashlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from docrelay.domain.enums import (
    ConnectionStatus,
    Provider,
    SyncMode,
    WatchItemOutcome,
    WatchScanStatus,
    WatchScanTrigger,
    WatchVersionStatus,
    WriteAuthorizationState,
)
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.oauth import GOOGLE_WATCH_SCOPES
from docrelay.integrations.google.read_only import (
    DRIVE_FOLDER_MIME,
    GOOGLE_DOC_MIME,
    GoogleFileMetadata,
    GoogleReadPort,
)
from docrelay.integrations.google.services import GoogleConnectionService, RegisteredBaseline
from docrelay.persistence.models import (
    AuditEvent,
    CloudConnection,
    FolderRule,
    WatchConfig,
    WatchDocumentVersion,
    WatchedItem,
    WatchRunLink,
    WatchScan,
    WatchScanItem,
)
from docrelay.services.superdocs_workflow import (
    RunView,
    SuperDocsBaseline,
    SuperDocsWorkflow,
    WorkflowRuleContext,
)

WATCH_RULE_SCHEMA = "docrelay.watch-folder-rule.v1"
WATCH_DISCOVERY_SCHEMA = "docrelay.google-folder-discovery.v1"
ACTIVE_SCAN_KEY = "ACTIVE"
MAX_FOLDER_DEPTH = 100


class WatchError(RuntimeError):
    code = "WATCH_ERROR"

    def __init__(self, message: str) -> None:
        self.safe_message = message
        super().__init__(message)


class WatchNotFound(WatchError):
    code = "WATCH_NOT_FOUND"


class WatchInvalidRoot(WatchError):
    code = "WATCH_INVALID_ROOT"


class WatchRuleFolderInvalid(WatchError):
    code = "WATCH_RULE_FOLDER_INVALID"


class WatchDiscoveryFailed(WatchError):
    code = "WATCH_DISCOVERY_FAILED"


class WatchClaimLost(WatchError):
    code = "WATCH_CLAIM_LOST"


class WatchItemOutOfScope(WatchError):
    code = "WATCH_ITEM_OUT_OF_SCOPE"


class ExactFileAuthorizationMismatch(WatchError):
    code = "EXACT_FILE_AUTHORIZATION_MISMATCH"


class WatchGoogleOperations(Protocol):
    async def watch_read_client(self, connection_id: UUID) -> GoogleReadPort: ...

    async def require_watch_authorization(self, connection_id: UUID) -> None: ...

    async def register_and_capture(
        self,
        *,
        connection_id: UUID,
        file_id: str,
        required_scopes: tuple[str, ...],
    ) -> RegisteredBaseline: ...

    async def verify_exact_file_write_authorization(
        self, *, connection_id: UUID, file_id: str
    ) -> GoogleFileMetadata: ...


GoogleFactory = Callable[[AsyncSession], WatchGoogleOperations]


class WatchRunStarter(Protocol):
    async def start_run(
        self,
        *,
        baseline: SuperDocsBaseline,
        instruction: str,
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        rule_context: WorkflowRuleContext | None = None,
    ) -> RunView: ...


@dataclass(frozen=True, slots=True)
class WatchClaim:
    watch_config_id: UUID
    scan_id: UUID
    lease_token: UUID
    trigger: WatchScanTrigger


@dataclass(frozen=True, slots=True)
class ClaimResult:
    claim: WatchClaim | None
    scan_id: UUID


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    rule_id: UUID
    version: int
    folder_id: str
    instruction: str
    instruction_sha256: str
    configuration: dict[str, JsonValue]
    supported_formats: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DiscoveredItem:
    metadata: GoogleFileMetadata
    ancestor_folder_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedVersion:
    watched_item_id: UUID
    version_id: UUID
    provider_version: str
    discovery_kind: str
    rule: ResolvedRule
    rule_snapshot: dict[str, JsonValue]


class WatchService:
    """Persisted scheduler/discovery layer that feeds the SuperDocs workflow."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        owner_subject: str,
        google_factory: GoogleFactory,
        runs: WatchRunStarter,
        scan_lease_seconds: int = 300,
        max_items_per_scan: int = 5000,
    ) -> None:
        if scan_lease_seconds < 30:
            raise ValueError("watch scan lease must be at least 30 seconds")
        if max_items_per_scan < 1:
            raise ValueError("watch scan item limit must be positive")
        self._sessions = sessions
        self._owner_subject = owner_subject
        self._google_factory = google_factory
        self._runs = runs
        self._scan_lease = timedelta(seconds=scan_lease_seconds)
        self._max_items = max_items_per_scan

    async def configure_root(
        self,
        *,
        connection_id: UUID,
        root_folder_id: str,
        interval_seconds: int,
        enabled: bool,
    ) -> WatchConfig:
        _validate_interval(interval_seconds)
        async with self._sessions() as session:
            provider = await self._google_factory(session).watch_read_client(connection_id)
            metadata = await provider.get_file(root_folder_id)
            _validate_folder(metadata, expected_id=root_folder_id, root=True)
            connection = await session.scalar(
                select(CloudConnection)
                .where(
                    CloudConnection.id == connection_id,
                    CloudConnection.owner_subject == self._owner_subject,
                    CloudConnection.provider == Provider.GOOGLE,
                )
                .with_for_update()
            )
            if connection is None:
                raise WatchNotFound("Google connection for watched root was not found")
            watch = await session.scalar(
                select(WatchConfig).where(
                    WatchConfig.connection_id == connection_id,
                    WatchConfig.parent_folder_id == root_folder_id,
                )
            )
            now = datetime.now(UTC)
            if watch is None:
                watch = WatchConfig(
                    connection_id=connection_id,
                    parent_folder_id=root_folder_id,
                    root_name=metadata.name,
                    schedule="interval",
                    timezone="UTC",
                    interval_seconds=interval_seconds,
                    default_mode=SyncMode.PREVIEW,
                    enabled=enabled,
                    next_scan_at=now if enabled else None,
                )
                session.add(watch)
                await session.flush()
                session.add(
                    AuditEvent(
                        connection_id=connection_id,
                        actor_subject=self._owner_subject,
                        event_type="GOOGLE_WATCH_ROOT_CONFIGURED",
                        safe_payload={
                            "watch_config_id": str(watch.id),
                            "root_folder_id": root_folder_id,
                            "interval_seconds": interval_seconds,
                            "enabled": enabled,
                            "provider_subset": "MY_DRIVE_NO_SHARED_DRIVES",
                        },
                    )
                )
            else:
                watch.root_name = metadata.name
                watch.interval_seconds = interval_seconds
                if watch.enabled != enabled:
                    watch.enabled = enabled
                    watch.next_scan_at = now if enabled else None
            await session.commit()
            return watch

    async def list_watches(self) -> tuple[WatchConfig, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(WatchConfig)
                .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
                .where(
                    CloudConnection.owner_subject == self._owner_subject,
                    CloudConnection.provider == Provider.GOOGLE,
                )
                .order_by(WatchConfig.created_at, WatchConfig.id)
            )
            return tuple(rows)

    async def get_watch(self, watch_id: UUID) -> WatchConfig:
        async with self._sessions() as session:
            return await self._owned_watch(session, watch_id)

    async def set_schedule(
        self, watch_id: UUID, *, enabled: bool, interval_seconds: int
    ) -> WatchConfig:
        _validate_interval(interval_seconds)
        async with self._sessions() as session:
            watch = await self._owned_watch(session, watch_id)
            if enabled:
                await self._google_factory(session).require_watch_authorization(watch.connection_id)
            watch = await self._owned_watch(session, watch_id, for_update=True)
            now = datetime.now(UTC)
            watch.enabled = enabled
            watch.interval_seconds = interval_seconds
            watch.schedule = "interval"
            watch.timezone = "UTC"
            watch.next_scan_at = now if enabled else None
            session.add(
                AuditEvent(
                    connection_id=watch.connection_id,
                    actor_subject=self._owner_subject,
                    event_type="GOOGLE_WATCH_SCHEDULE_CHANGED",
                    safe_payload={
                        "watch_config_id": str(watch.id),
                        "enabled": enabled,
                        "interval_seconds": interval_seconds,
                    },
                )
            )
            await session.commit()
            return watch

    async def configure_rule(
        self,
        watch_id: UUID,
        *,
        folder_id: str,
        instruction: str,
        enabled: bool,
    ) -> FolderRule:
        normalized_instruction = instruction.strip()
        if not normalized_instruction:
            raise ValueError("watch rule instruction must not be empty")
        async with self._sessions() as session:
            watch = await self._owned_watch(session, watch_id)
            provider = await self._google_factory(session).watch_read_client(watch.connection_id)
            path, folder_name = await _folder_path_to_root(
                provider,
                root_id=watch.parent_folder_id,
                folder_id=folder_id,
            )
            watch = await self._owned_watch(session, watch_id, for_update=True)
            latest_version = await session.scalar(
                select(func.max(FolderRule.version)).where(
                    FolderRule.watch_config_id == watch.id,
                    FolderRule.provider_folder_id == folder_id,
                )
            )
            rule = FolderRule(
                watch_config_id=watch.id,
                provider_folder_id=folder_id,
                version=int(latest_version or 0) + 1,
                instruction=normalized_instruction,
                instruction_sha256=_sha256_text(normalized_instruction),
                configuration={
                    "schema": WATCH_RULE_SCHEMA,
                    "folder_name": folder_name,
                    "ancestor_folder_ids": list(path),
                    "precedence": "nearest_enabled_ancestor",
                },
                supported_formats={"mime_types": [GOOGLE_DOC_MIME]},
                active=enabled,
            )
            session.add(rule)
            await session.flush()
            session.add(
                AuditEvent(
                    connection_id=watch.connection_id,
                    actor_subject=self._owner_subject,
                    event_type="GOOGLE_WATCH_RULE_VERSION_CREATED",
                    safe_payload={
                        "watch_config_id": str(watch.id),
                        "folder_id": folder_id,
                        "rule_id": str(rule.id),
                        "version": rule.version,
                        "enabled": enabled,
                        "instruction_sha256": rule.instruction_sha256,
                    },
                )
            )
            await session.commit()
            return rule

    async def list_rules(self, watch_id: UUID) -> tuple[FolderRule, ...]:
        async with self._sessions() as session:
            await self._owned_watch(session, watch_id)
            rows = (
                await session.scalars(
                    select(FolderRule)
                    .where(FolderRule.watch_config_id == watch_id)
                    .order_by(FolderRule.provider_folder_id, FolderRule.version.desc())
                )
            ).all()
            latest: dict[str, FolderRule] = {}
            for row in rows:
                latest.setdefault(row.provider_folder_id, row)
            return tuple(sorted(latest.values(), key=lambda row: row.provider_folder_id))

    async def claim_due(self, *, limit: int = 10) -> tuple[WatchClaim, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("watch claim limit must be between 1 and 100")
        now = datetime.now(UTC)
        claims: list[WatchClaim] = []
        async with self._sessions() as session:
            expired = (
                await session.scalars(
                    select(WatchScan)
                    .join(WatchConfig, WatchConfig.id == WatchScan.watch_config_id)
                    .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
                    .where(
                        CloudConnection.owner_subject == self._owner_subject,
                        CloudConnection.provider == Provider.GOOGLE,
                        WatchScan.status == WatchScanStatus.RUNNING,
                        WatchScan.active_key == ACTIVE_SCAN_KEY,
                        WatchScan.lease_expires_at <= now,
                    )
                    .order_by(WatchScan.lease_expires_at, WatchScan.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for scan in expired:
                claims.append(self._reclaim(scan, now))
            remaining = limit - len(claims)
            if remaining:
                active_scan_exists = (
                    select(WatchScan.id)
                    .where(
                        WatchScan.watch_config_id == WatchConfig.id,
                        WatchScan.status == WatchScanStatus.RUNNING,
                        WatchScan.active_key == ACTIVE_SCAN_KEY,
                    )
                    .exists()
                )
                due = (
                    await session.scalars(
                        select(WatchConfig)
                        .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
                        .where(
                            CloudConnection.owner_subject == self._owner_subject,
                            CloudConnection.provider == Provider.GOOGLE,
                            CloudConnection.status == ConnectionStatus.CONNECTED,
                            WatchConfig.enabled.is_(True),
                            WatchConfig.next_scan_at.is_not(None),
                            WatchConfig.next_scan_at <= now,
                            ~active_scan_exists,
                        )
                        .order_by(WatchConfig.next_scan_at, WatchConfig.id)
                        .limit(remaining)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                for watch in due:
                    active = await self._active_scan(session, watch.id, for_update=True)
                    if active is not None:
                        continue
                    claims.append(
                        await self._new_claim(
                            session,
                            watch,
                            trigger=WatchScanTrigger.SCHEDULED,
                            now=now,
                        )
                    )
            await session.commit()
        return tuple(claims)

    async def claim_manual(self, watch_id: UUID) -> ClaimResult:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            watch = await self._owned_watch(session, watch_id)
            await self._google_factory(session).require_watch_authorization(watch.connection_id)
            watch = await self._owned_watch(session, watch_id, for_update=True)
            active = await self._active_scan(session, watch.id, for_update=True)
            if active is not None and _as_utc(active.lease_expires_at) > now:
                return ClaimResult(claim=None, scan_id=active.id)
            if active is not None:
                claim = self._reclaim(active, now)
            else:
                claim = await self._new_claim(
                    session,
                    watch,
                    trigger=WatchScanTrigger.MANUAL,
                    now=now,
                )
            await session.commit()
            return ClaimResult(claim=claim, scan_id=claim.scan_id)

    async def trigger_manual(self, watch_id: UUID) -> WatchScan:
        result = await self.claim_manual(watch_id)
        if result.claim is not None:
            return await self.execute_claim(result.claim)
        return await self.get_scan(result.scan_id)

    async def execute_claim(self, claim: WatchClaim) -> WatchScan:
        try:
            watch, rules, provider = await self._scan_context(claim)
            discovered = await self._discover(claim, provider, watch)
            for item in discovered:
                await self._renew_claim(claim)
                try:
                    await self._process_item(
                        claim=claim,
                        watch=watch,
                        rules=rules,
                        provider=provider,
                        item=item,
                    )
                except GoogleIntegrationError as exc:
                    await self._record_item_failure(claim, item, exc.code.value)
                    if exc.code in {
                        GoogleErrorCode.REAUTH_REQUIRED,
                        GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED,
                    }:
                        raise
                except WatchItemOutOfScope as exc:
                    await self._record_item_out_of_scope(claim, item, exc.code)
                except WatchClaimLost:
                    raise
                except WatchError as exc:
                    await self._record_item_failure(claim, item, exc.code)
                except Exception:
                    await self._record_item_failure(claim, item, "WATCH_ITEM_PROCESSING_FAILED")
            await self._mark_items_out_of_scope(claim)
            return await self._complete_scan(claim)
        except WatchClaimLost:
            raise
        except GoogleIntegrationError as exc:
            return await self._fail_scan(claim, exc.code.value)
        except WatchError as exc:
            return await self._fail_scan(claim, exc.code)
        except Exception:
            return await self._fail_scan(claim, "WATCH_SCAN_FAILED")

    async def get_scan(self, scan_id: UUID) -> WatchScan:
        async with self._sessions() as session:
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

    async def list_scans(self, watch_id: UUID, *, limit: int = 50) -> tuple[WatchScan, ...]:
        async with self._sessions() as session:
            await self._owned_watch(session, watch_id)
            rows = await session.scalars(
                select(WatchScan)
                .where(WatchScan.watch_config_id == watch_id)
                .order_by(WatchScan.started_at.desc(), WatchScan.id.desc())
                .limit(limit)
            )
            return tuple(rows)

    async def list_scan_items(self, scan_id: UUID) -> tuple[WatchScanItem, ...]:
        await self.get_scan(scan_id)
        async with self._sessions() as session:
            rows = await session.scalars(
                select(WatchScanItem)
                .where(WatchScanItem.watch_scan_id == scan_id)
                .order_by(WatchScanItem.provider_file_id)
            )
            return tuple(rows)

    async def list_items(self, watch_id: UUID) -> tuple[WatchedItem, ...]:
        async with self._sessions() as session:
            await self._owned_watch(session, watch_id)
            rows = await session.scalars(
                select(WatchedItem)
                .where(WatchedItem.watch_config_id == watch_id)
                .order_by(WatchedItem.provider_file_id)
            )
            return tuple(rows)

    async def verify_run_write_authorization(
        self, run_id: UUID, *, picker_file_id: str
    ) -> WatchRunLink:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(WatchRunLink, WatchedItem, WatchConfig)
                    .join(WatchedItem, WatchedItem.id == WatchRunLink.watched_item_id)
                    .join(WatchConfig, WatchConfig.id == WatchRunLink.watch_config_id)
                    .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
                    .where(
                        WatchRunLink.sync_run_id == run_id,
                        CloudConnection.owner_subject == self._owner_subject,
                    )
                )
            ).one_or_none()
            if row is None:
                raise WatchNotFound("watched run was not found")
            _link, item, watch = row._tuple()
            if picker_file_id != item.provider_file_id:
                raise ExactFileAuthorizationMismatch(
                    "Picker authorization did not match the watched document identity"
                )
            if not item.current_in_scope:
                raise ExactFileAuthorizationMismatch(
                    "watched document is no longer inside the configured root"
                )
            google = self._google_factory(session)
            metadata = await google.verify_exact_file_write_authorization(
                connection_id=watch.connection_id,
                file_id=item.provider_file_id,
            )
            try:
                await _validate_document_path(
                    await google.watch_read_client(watch.connection_id),
                    root_id=watch.parent_folder_id,
                    ancestor_folder_ids=tuple(item.ancestor_folder_ids),
                    metadata=metadata,
                )
            except WatchError as exc:
                raise ExactFileAuthorizationMismatch(
                    "Google document is no longer in its watched folder path"
                ) from exc
            if (
                metadata.mime_type != GOOGLE_DOC_MIME
                or metadata.trashed
                or metadata.drive_id is not None
            ):
                raise ExactFileAuthorizationMismatch(
                    "Google no longer reports the expected writable My Drive document"
                )
            locked = (
                await session.execute(
                    select(WatchRunLink, WatchedItem, WatchConfig)
                    .join(WatchedItem, WatchedItem.id == WatchRunLink.watched_item_id)
                    .join(WatchConfig, WatchConfig.id == WatchRunLink.watch_config_id)
                    .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
                    .where(
                        WatchRunLink.sync_run_id == run_id,
                        CloudConnection.owner_subject == self._owner_subject,
                    )
                    .with_for_update()
                )
            ).one_or_none()
            if locked is None:
                raise WatchNotFound("watched run was not found")
            link, item, _watch = locked._tuple()
            if item.provider_file_id != picker_file_id:
                raise ExactFileAuthorizationMismatch(
                    "watched document identity changed during authorization verification"
                )
            if not item.current_in_scope:
                raise ExactFileAuthorizationMismatch(
                    "watched document left the configured root during authorization verification"
                )
            now = datetime.now(UTC)
            state = (
                WriteAuthorizationState.AUTHORIZED
                if metadata.is_app_authorized is True
                else WriteAuthorizationState.REQUIRED
            )
            link.write_authorization_state = state
            link.write_authorization_checked_at = now
            link.write_authorization_evidence = {
                "provider_file_id": item.provider_file_id,
                "is_app_authorized": metadata.is_app_authorized is True,
                "verified_via": "drive.files.get.isAppAuthorized",
                "read_scope_is_not_write_authority": True,
            }
            item.write_authorization_state = state
            item.write_authorization_checked_at = now
            await session.commit()
            return link

    async def _scan_context(
        self, claim: WatchClaim
    ) -> tuple[WatchConfig, tuple[ResolvedRule, ...], GoogleReadPort]:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            watch = await self._owned_watch(session, claim.watch_config_id)
            provider = await self._google_factory(session).watch_read_client(watch.connection_id)
            rules = await self._current_rules(session, watch.id)
            return watch, rules, provider

    async def _discover(
        self, claim: WatchClaim, provider: GoogleReadPort, watch: WatchConfig
    ) -> tuple[DiscoveredItem, ...]:
        await self._renew_claim(claim)
        root = await provider.get_file(watch.parent_folder_id)
        _validate_folder(root, expected_id=watch.parent_folder_id, root=True)
        queue: deque[tuple[str, tuple[str, ...]]] = deque(
            [(watch.parent_folder_id, (watch.parent_folder_id,))]
        )
        visited_folders = {watch.parent_folder_id}
        visited_items: set[str] = set()
        leaves: list[DiscoveredItem] = []
        item_count = 0
        while queue:
            folder_id, path = queue.popleft()
            if len(path) > MAX_FOLDER_DEPTH:
                raise WatchDiscoveryFailed("watched folder depth exceeded the safe limit")
            page_token: str | None = None
            seen_tokens: set[str] = set()
            while True:
                await self._renew_claim(claim)
                await _validate_folder_path(
                    provider,
                    root_id=watch.parent_folder_id,
                    ancestor_folder_ids=path,
                )
                page = await provider.list_children(folder_id, page_token=page_token)
                await _validate_folder_path(
                    provider,
                    root_id=watch.parent_folder_id,
                    ancestor_folder_ids=path,
                )
                if page.incomplete_search:
                    raise WatchDiscoveryFailed("Google Drive returned an incomplete folder search")
                for metadata in page.items:
                    item_count += 1
                    if item_count > self._max_items:
                        raise WatchDiscoveryFailed("watched folder exceeded the scan item limit")
                    _validate_child(metadata, expected_parent_id=folder_id)
                    if metadata.file_id in visited_items:
                        raise WatchDiscoveryFailed(
                            "Google Drive returned a duplicate descendant identity"
                        )
                    visited_items.add(metadata.file_id)
                    if metadata.mime_type == DRIVE_FOLDER_MIME:
                        if metadata.file_id in visited_folders:
                            raise WatchDiscoveryFailed(
                                "Google Drive returned a cyclic or duplicate folder hierarchy"
                            )
                        visited_folders.add(metadata.file_id)
                        queue.append((metadata.file_id, (*path, metadata.file_id)))
                    else:
                        leaves.append(
                            DiscoveredItem(
                                metadata=metadata,
                                ancestor_folder_ids=path,
                            )
                        )
                next_token = page.next_page_token
                if next_token is None:
                    break
                if next_token in seen_tokens:
                    raise WatchDiscoveryFailed("Google Drive pagination cursor repeated")
                seen_tokens.add(next_token)
                page_token = next_token
        return tuple(
            sorted(
                leaves,
                key=lambda item: (item.ancestor_folder_ids, item.metadata.file_id),
            )
        )

    async def _process_item(
        self,
        *,
        claim: WatchClaim,
        watch: WatchConfig,
        rules: tuple[ResolvedRule, ...],
        provider: GoogleReadPort,
        item: DiscoveredItem,
    ) -> None:
        metadata = item.metadata
        if metadata.mime_type != GOOGLE_DOC_MIME:
            await self._record_simple_observation(
                claim,
                item,
                outcome=WatchItemOutcome.UNSUPPORTED,
                reason_code="UNSUPPORTED_MIME_TYPE",
            )
            return
        if metadata.provider_version is None:
            await self._record_simple_observation(
                claim,
                item,
                outcome=WatchItemOutcome.FAILED,
                reason_code="PROVIDER_VERSION_MISSING",
            )
            return
        pre_capture = await provider.get_file(metadata.file_id)
        await _validate_document_path(
            provider,
            root_id=watch.parent_folder_id,
            ancestor_folder_ids=item.ancestor_folder_ids,
            metadata=pre_capture,
        )
        if pre_capture.provider_version != metadata.provider_version:
            raise WatchDiscoveryFailed("Google document version changed before immutable capture")
        prepared = await self._prepare_version(claim, watch, rules, item)
        if prepared is None:
            return
        await self._renew_claim(claim)
        async with self._sessions() as session:
            registered = await self._google_factory(session).register_and_capture(
                connection_id=watch.connection_id,
                file_id=metadata.file_id,
                required_scopes=GOOGLE_WATCH_SCOPES,
            )
        post_capture = await provider.get_file(metadata.file_id)
        await _validate_document_path(
            provider,
            root_id=watch.parent_folder_id,
            ancestor_folder_ids=item.ancestor_folder_ids,
            metadata=post_capture,
        )
        if (
            registered.result.metadata.provider_version != prepared.provider_version
            or post_capture.provider_version != prepared.provider_version
        ):
            raise WatchDiscoveryFailed(
                "Google document version changed between discovery and immutable capture"
            )
        rule_context = WorkflowRuleContext(
            folder_rule_id=prepared.rule.rule_id,
            folder_rule_version=prepared.rule.version,
            intent_discriminator=f"watch-document-version:{prepared.version_id}",
            rule_snapshot=prepared.rule_snapshot,
        )
        await self._renew_claim(claim)
        run = await self._runs.start_run(
            baseline=_superdocs_baseline(registered),
            instruction=prepared.rule.instruction,
            rule_context=rule_context,
        )
        await self._link_run(
            claim=claim,
            prepared=prepared,
            registered=registered,
            run=run,
            item=item,
        )

    async def _prepare_version(
        self,
        claim: WatchClaim,
        watch: WatchConfig,
        rules: tuple[ResolvedRule, ...],
        discovered: DiscoveredItem,
    ) -> PreparedVersion | None:
        metadata = discovered.metadata
        assert metadata.provider_version is not None
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            watched = await session.scalar(
                select(WatchedItem)
                .where(
                    WatchedItem.watch_config_id == watch.id,
                    WatchedItem.provider_file_id == metadata.file_id,
                )
                .with_for_update()
            )
            discovery_kind = "NEW"
            if watched is None:
                watched = WatchedItem(
                    watch_config_id=watch.id,
                    provider_file_id=metadata.file_id,
                    display_name=metadata.name,
                    mime_type=metadata.mime_type,
                    provider_version=metadata.provider_version,
                    provider_modified_at=metadata.modified_time,
                    parent_folder_id=discovered.ancestor_folder_ids[-1],
                    ancestor_folder_ids=list(discovered.ancestor_folder_ids),
                    current_in_scope=True,
                    last_seen_scan_id=claim.scan_id,
                    last_seen_at=datetime.now(UTC),
                    write_authorization_state=_authorization_state(metadata),
                    write_authorization_checked_at=datetime.now(UTC),
                )
                session.add(watched)
                await session.flush()
            else:
                if watched.provider_version == metadata.provider_version:
                    discovery_kind = "SEEN"
                else:
                    discovery_kind = "CHANGED"
                watched.display_name = metadata.name
                watched.mime_type = metadata.mime_type
                watched.provider_version = metadata.provider_version
                watched.provider_modified_at = metadata.modified_time
                watched.parent_folder_id = discovered.ancestor_folder_ids[-1]
                watched.ancestor_folder_ids = list(discovered.ancestor_folder_ids)
                watched.current_in_scope = True
                watched.last_seen_scan_id = claim.scan_id
                watched.last_seen_at = datetime.now(UTC)
                watched.write_authorization_state = _authorization_state(metadata)
                watched.write_authorization_checked_at = datetime.now(UTC)

            version = await session.scalar(
                select(WatchDocumentVersion)
                .where(
                    WatchDocumentVersion.watched_item_id == watched.id,
                    WatchDocumentVersion.provider_version == metadata.provider_version,
                )
                .with_for_update()
            )
            if version is None:
                version = WatchDocumentVersion(
                    watched_item_id=watched.id,
                    first_seen_scan_id=claim.scan_id,
                    provider_version=metadata.provider_version,
                    provider_modified_at=metadata.modified_time,
                    status=WatchVersionStatus.DISCOVERED,
                )
                session.add(version)
                await session.flush()
            if version.status is WatchVersionStatus.ENQUEUED and version.sync_run_id is not None:
                await self._upsert_scan_item(
                    session,
                    claim=claim,
                    discovered=discovered,
                    watched=watched,
                    version=version,
                    run_id=version.sync_run_id,
                    discovery_kind=discovery_kind,
                    outcome=WatchItemOutcome.UNCHANGED,
                    reason_code="ALREADY_ENQUEUED_VERSION",
                    rule_id=version.folder_rule_id,
                    rule_version=version.folder_rule_version,
                )
                await self._sync_authorization_state(
                    session, version.sync_run_id, watched.write_authorization_state
                )
                await session.commit()
                return None

            rule = _resolve_rule(rules, discovered.ancestor_folder_ids)
            if version.rule_snapshot is None:
                if rule is None:
                    version.status = WatchVersionStatus.NO_RULE
                    version.failure_code = "NO_APPLICABLE_RULE"
                    await self._upsert_scan_item(
                        session,
                        claim=claim,
                        discovered=discovered,
                        watched=watched,
                        version=version,
                        run_id=None,
                        discovery_kind=discovery_kind,
                        outcome=WatchItemOutcome.NO_RULE,
                        reason_code="NO_APPLICABLE_RULE",
                    )
                    await session.commit()
                    return None
                snapshot = _rule_snapshot(
                    watch=watch,
                    version_id=version.id,
                    rule=rule,
                    ancestor_folder_ids=discovered.ancestor_folder_ids,
                )
                version.folder_rule_id = rule.rule_id
                version.folder_rule_version = rule.version
                version.rule_snapshot = snapshot
            else:
                rule = await self._frozen_rule(session, version)
                snapshot = dict(version.rule_snapshot)
            version.status = WatchVersionStatus.ENQUEUE_PENDING
            version.failure_code = None
            version.failure_detail = None
            await session.commit()
            return PreparedVersion(
                watched_item_id=watched.id,
                version_id=version.id,
                provider_version=metadata.provider_version,
                discovery_kind=discovery_kind,
                rule=rule,
                rule_snapshot=snapshot,
            )

    async def _link_run(
        self,
        *,
        claim: WatchClaim,
        prepared: PreparedVersion,
        registered: RegisteredBaseline,
        run: RunView,
        item: DiscoveredItem,
    ) -> None:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            version = await session.get(
                WatchDocumentVersion, prepared.version_id, with_for_update=True
            )
            watched = await session.get(WatchedItem, prepared.watched_item_id, with_for_update=True)
            if version is None or watched is None:
                raise WatchDiscoveryFailed("watched document checkpoint disappeared")
            if version.sync_run_id is not None and version.sync_run_id != run.run_id:
                raise WatchDiscoveryFailed("watched document version linked to another run")
            state = _authorization_state(registered.result.metadata)
            link = await session.scalar(
                select(WatchRunLink).where(WatchRunLink.watch_document_version_id == version.id)
            )
            now = datetime.now(UTC)
            if link is None:
                link = WatchRunLink(
                    watch_config_id=claim.watch_config_id,
                    watch_scan_id=claim.scan_id,
                    watched_item_id=watched.id,
                    watch_document_version_id=version.id,
                    sync_run_id=run.run_id,
                    folder_rule_id=prepared.rule.rule_id,
                    folder_rule_version=prepared.rule.version,
                    rule_snapshot=prepared.rule_snapshot,
                    write_authorization_state=state,
                    write_authorization_checked_at=now,
                    write_authorization_evidence={
                        "provider_file_id": item.metadata.file_id,
                        "is_app_authorized": state is WriteAuthorizationState.AUTHORIZED,
                        "verified_via": "drive.files.get during immutable capture",
                        "read_scope_is_not_write_authority": True,
                    },
                )
                session.add(link)
            version.status = WatchVersionStatus.ENQUEUED
            version.provider_revision_id = registered.result.revision_id
            version.sync_run_id = run.run_id
            version.failure_code = None
            version.failure_detail = None
            watched.cloud_document_id = registered.document.id
            watched.last_enqueued_provider_version = prepared.provider_version
            watched.last_enqueued_revision_id = registered.result.revision_id
            watched.last_enqueued_run_id = run.run_id
            watched.write_authorization_state = state
            watched.write_authorization_checked_at = now
            await self._upsert_scan_item(
                session,
                claim=claim,
                discovered=item,
                watched=watched,
                version=version,
                run_id=run.run_id,
                discovery_kind=prepared.discovery_kind,
                outcome=WatchItemOutcome.ENQUEUED,
                reason_code=None,
                rule_id=prepared.rule.rule_id,
                rule_version=prepared.rule.version,
            )
            await session.commit()

    async def _record_simple_observation(
        self,
        claim: WatchClaim,
        item: DiscoveredItem,
        *,
        outcome: WatchItemOutcome,
        reason_code: str,
    ) -> None:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            await self._upsert_scan_item(
                session,
                claim=claim,
                discovered=item,
                watched=None,
                version=None,
                run_id=None,
                discovery_kind="SEEN",
                outcome=outcome,
                reason_code=reason_code,
            )
            await session.commit()

    async def _record_item_failure(
        self, claim: WatchClaim, item: DiscoveredItem, reason_code: str
    ) -> None:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            watched = await session.scalar(
                select(WatchedItem).where(
                    WatchedItem.watch_config_id == claim.watch_config_id,
                    WatchedItem.provider_file_id == item.metadata.file_id,
                )
            )
            version = None
            if watched is not None and item.metadata.provider_version is not None:
                version = await session.scalar(
                    select(WatchDocumentVersion).where(
                        WatchDocumentVersion.watched_item_id == watched.id,
                        WatchDocumentVersion.provider_version == item.metadata.provider_version,
                    )
                )
                if version is not None and version.status is not WatchVersionStatus.ENQUEUED:
                    version.status = WatchVersionStatus.FAILED
                    version.failure_code = reason_code
                    version.failure_detail = {}
            await self._upsert_scan_item(
                session,
                claim=claim,
                discovered=item,
                watched=watched,
                version=version,
                run_id=version.sync_run_id if version is not None else None,
                discovery_kind="CHANGED" if watched is not None else "NEW",
                outcome=WatchItemOutcome.FAILED,
                reason_code=reason_code,
                rule_id=version.folder_rule_id if version is not None else None,
                rule_version=version.folder_rule_version if version is not None else None,
            )
            await session.commit()

    async def _record_item_out_of_scope(
        self, claim: WatchClaim, item: DiscoveredItem, reason_code: str
    ) -> None:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            watched = await session.scalar(
                select(WatchedItem).where(
                    WatchedItem.watch_config_id == claim.watch_config_id,
                    WatchedItem.provider_file_id == item.metadata.file_id,
                )
            )
            version = None
            if watched is not None:
                watched.current_in_scope = False
                if item.metadata.provider_version is not None:
                    version = await session.scalar(
                        select(WatchDocumentVersion).where(
                            WatchDocumentVersion.watched_item_id == watched.id,
                            WatchDocumentVersion.provider_version == item.metadata.provider_version,
                        )
                    )
                    if version is not None and version.status is not WatchVersionStatus.ENQUEUED:
                        version.status = WatchVersionStatus.FAILED
                        version.failure_code = reason_code
                        version.failure_detail = {}
            await self._upsert_scan_item(
                session,
                claim=claim,
                discovered=item,
                watched=watched,
                version=version,
                run_id=version.sync_run_id if version is not None else None,
                discovery_kind="CHANGED" if watched is not None else "NEW",
                outcome=WatchItemOutcome.OUT_OF_SCOPE,
                reason_code=reason_code,
                rule_id=version.folder_rule_id if version is not None else None,
                rule_version=version.folder_rule_version if version is not None else None,
            )
            await session.commit()

    async def _mark_items_out_of_scope(self, claim: WatchClaim) -> None:
        async with self._sessions() as session:
            await self._assert_claim(session, claim)
            missing = (
                await session.scalars(
                    select(WatchedItem)
                    .where(
                        WatchedItem.watch_config_id == claim.watch_config_id,
                        WatchedItem.current_in_scope.is_(True),
                        WatchedItem.last_seen_scan_id != claim.scan_id,
                    )
                    .with_for_update()
                )
            ).all()
            for watched in missing:
                watched.current_in_scope = False
                existing = await session.scalar(
                    select(WatchScanItem).where(
                        WatchScanItem.watch_scan_id == claim.scan_id,
                        WatchScanItem.provider_file_id == watched.provider_file_id,
                    )
                )
                if existing is None:
                    session.add(
                        WatchScanItem(
                            watch_scan_id=claim.scan_id,
                            watched_item_id=watched.id,
                            sync_run_id=watched.last_enqueued_run_id,
                            provider_file_id=watched.provider_file_id,
                            provider_version=watched.provider_version,
                            display_name=watched.display_name,
                            mime_type=watched.mime_type,
                            ancestor_folder_ids=list(watched.ancestor_folder_ids),
                            discovery_kind="MISSING",
                            outcome=WatchItemOutcome.OUT_OF_SCOPE,
                            reason_code="MOVED_DELETED_OR_TRASHED",
                        )
                    )
            await session.commit()

    async def _complete_scan(self, claim: WatchClaim) -> WatchScan:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            scan = await self._assert_claim(session, claim, for_update=True)
            watch = await self._owned_watch(session, claim.watch_config_id, for_update=True)
            rows = (
                await session.scalars(
                    select(WatchScanItem).where(WatchScanItem.watch_scan_id == scan.id)
                )
            ).all()
            scan.discovered_count = sum(
                row.outcome is not WatchItemOutcome.OUT_OF_SCOPE for row in rows
            )
            scan.changed_count = sum(row.discovery_kind == "CHANGED" for row in rows)
            scan.unchanged_count = sum(row.outcome is WatchItemOutcome.UNCHANGED for row in rows)
            scan.enqueued_count = sum(row.outcome is WatchItemOutcome.ENQUEUED for row in rows)
            scan.skipped_count = sum(
                row.outcome
                in {
                    WatchItemOutcome.NO_RULE,
                    WatchItemOutcome.UNSUPPORTED,
                    WatchItemOutcome.OUT_OF_SCOPE,
                }
                for row in rows
            )
            scan.failed_count = sum(row.outcome is WatchItemOutcome.FAILED for row in rows)
            scan.status = WatchScanStatus.SUCCEEDED
            scan.active_key = None
            scan.completed_at = now
            scan.failure_code = None
            scan.failure_detail = None
            watch.last_scan_at = now
            watch.last_successful_scan_at = now
            watch.last_scan_status = WatchScanStatus.SUCCEEDED
            watch.last_error_code = None
            watch.next_scan_at = (
                now + timedelta(seconds=watch.interval_seconds) if watch.enabled else None
            )
            session.add(
                AuditEvent(
                    connection_id=watch.connection_id,
                    actor_subject=self._owner_subject,
                    event_type="GOOGLE_WATCH_SCAN_SUCCEEDED",
                    safe_payload={
                        "watch_config_id": str(watch.id),
                        "watch_scan_id": str(scan.id),
                        "discovered_count": scan.discovered_count,
                        "unchanged_count": scan.unchanged_count,
                        "enqueued_count": scan.enqueued_count,
                        "skipped_count": scan.skipped_count,
                        "failed_count": scan.failed_count,
                    },
                )
            )
            await session.commit()
            return scan

    async def _fail_scan(self, claim: WatchClaim, failure_code: str) -> WatchScan:
        now = datetime.now(UTC)
        async with self._sessions() as session:
            scan = await self._assert_claim(session, claim, for_update=True)
            watch = await self._owned_watch(session, claim.watch_config_id, for_update=True)
            scan.status = WatchScanStatus.FAILED
            scan.active_key = None
            scan.completed_at = now
            scan.failure_code = failure_code
            scan.failure_detail = {}
            watch.last_scan_at = now
            watch.last_scan_status = WatchScanStatus.FAILED
            watch.last_error_code = failure_code
            watch.next_scan_at = (
                now + timedelta(seconds=watch.interval_seconds) if watch.enabled else None
            )
            session.add(
                AuditEvent(
                    connection_id=watch.connection_id,
                    actor_subject=self._owner_subject,
                    event_type="GOOGLE_WATCH_SCAN_FAILED",
                    safe_payload={
                        "watch_config_id": str(watch.id),
                        "watch_scan_id": str(scan.id),
                        "failure_code": failure_code,
                    },
                )
            )
            await session.commit()
            return scan

    async def _renew_claim(self, claim: WatchClaim) -> None:
        async with self._sessions() as session:
            scan = await self._assert_claim(session, claim, for_update=True)
            scan.lease_expires_at = datetime.now(UTC) + self._scan_lease
            await session.commit()

    async def _assert_claim(
        self,
        session: AsyncSession,
        claim: WatchClaim,
        *,
        for_update: bool = False,
    ) -> WatchScan:
        statement = select(WatchScan).where(
            WatchScan.id == claim.scan_id,
            WatchScan.watch_config_id == claim.watch_config_id,
        )
        if for_update:
            statement = statement.with_for_update()
        scan = await session.scalar(statement)
        if (
            scan is None
            or scan.status is not WatchScanStatus.RUNNING
            or scan.active_key != ACTIVE_SCAN_KEY
            or scan.lease_token != claim.lease_token
        ):
            raise WatchClaimLost("watch scan lease was reclaimed by another worker")
        return scan

    async def _new_claim(
        self,
        session: AsyncSession,
        watch: WatchConfig,
        *,
        trigger: WatchScanTrigger,
        now: datetime,
    ) -> WatchClaim:
        token = uuid4()
        scan = WatchScan(
            watch_config_id=watch.id,
            trigger=trigger,
            status=WatchScanStatus.RUNNING,
            active_key=ACTIVE_SCAN_KEY,
            lease_token=token,
            lease_expires_at=now + self._scan_lease,
            claim_generation=1,
            started_at=now,
        )
        session.add(scan)
        await session.flush()
        watch.last_scan_status = WatchScanStatus.RUNNING
        watch.last_error_code = None
        return WatchClaim(
            watch_config_id=watch.id,
            scan_id=scan.id,
            lease_token=token,
            trigger=trigger,
        )

    def _reclaim(self, scan: WatchScan, now: datetime) -> WatchClaim:
        token = uuid4()
        scan.lease_token = token
        scan.lease_expires_at = now + self._scan_lease
        scan.claim_generation += 1
        return WatchClaim(
            watch_config_id=scan.watch_config_id,
            scan_id=scan.id,
            lease_token=token,
            trigger=scan.trigger,
        )

    async def _active_scan(
        self, session: AsyncSession, watch_id: UUID, *, for_update: bool
    ) -> WatchScan | None:
        statement = select(WatchScan).where(
            WatchScan.watch_config_id == watch_id,
            WatchScan.status == WatchScanStatus.RUNNING,
            WatchScan.active_key == ACTIVE_SCAN_KEY,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _owned_watch(
        self, session: AsyncSession, watch_id: UUID, *, for_update: bool = False
    ) -> WatchConfig:
        statement = (
            select(WatchConfig)
            .join(CloudConnection, CloudConnection.id == WatchConfig.connection_id)
            .where(
                WatchConfig.id == watch_id,
                CloudConnection.owner_subject == self._owner_subject,
                CloudConnection.provider == Provider.GOOGLE,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        watch = await session.scalar(statement)
        if watch is None:
            raise WatchNotFound("watched Google Drive root was not found")
        return watch

    async def _current_rules(
        self, session: AsyncSession, watch_id: UUID
    ) -> tuple[ResolvedRule, ...]:
        rows = (
            await session.scalars(
                select(FolderRule)
                .where(FolderRule.watch_config_id == watch_id)
                .order_by(FolderRule.provider_folder_id, FolderRule.version.desc())
            )
        ).all()
        latest: dict[str, FolderRule] = {}
        for row in rows:
            latest.setdefault(row.provider_folder_id, row)
        return tuple(
            ResolvedRule(
                rule_id=row.id,
                version=row.version,
                folder_id=row.provider_folder_id,
                instruction=row.instruction,
                instruction_sha256=row.instruction_sha256,
                configuration=cast(dict[str, JsonValue], dict(row.configuration)),
                supported_formats=cast(dict[str, JsonValue], dict(row.supported_formats)),
            )
            for row in latest.values()
            if row.active
        )

    async def _frozen_rule(
        self, session: AsyncSession, version: WatchDocumentVersion
    ) -> ResolvedRule:
        if version.folder_rule_id is None or version.folder_rule_version is None:
            raise WatchDiscoveryFailed("frozen watch rule identity is incomplete")
        row = await session.get(FolderRule, version.folder_rule_id)
        if row is None or row.version != version.folder_rule_version:
            raise WatchDiscoveryFailed("frozen watch rule no longer exists")
        return ResolvedRule(
            rule_id=row.id,
            version=row.version,
            folder_id=row.provider_folder_id,
            instruction=row.instruction,
            instruction_sha256=row.instruction_sha256,
            configuration=cast(dict[str, JsonValue], dict(row.configuration)),
            supported_formats=cast(dict[str, JsonValue], dict(row.supported_formats)),
        )

    async def _sync_authorization_state(
        self,
        session: AsyncSession,
        run_id: UUID,
        state: WriteAuthorizationState,
    ) -> None:
        link = await session.scalar(select(WatchRunLink).where(WatchRunLink.sync_run_id == run_id))
        if link is not None:
            link.write_authorization_state = state
            link.write_authorization_checked_at = datetime.now(UTC)
            link.write_authorization_evidence = {
                "is_app_authorized": state is WriteAuthorizationState.AUTHORIZED,
                "verified_via": "drive.files.list.isAppAuthorized",
                "read_scope_is_not_write_authority": True,
            }

    async def _upsert_scan_item(
        self,
        session: AsyncSession,
        *,
        claim: WatchClaim,
        discovered: DiscoveredItem,
        watched: WatchedItem | None,
        version: WatchDocumentVersion | None,
        run_id: UUID | None,
        discovery_kind: str,
        outcome: WatchItemOutcome,
        reason_code: str | None,
        rule_id: UUID | None = None,
        rule_version: int | None = None,
    ) -> WatchScanItem:
        row = await session.scalar(
            select(WatchScanItem).where(
                WatchScanItem.watch_scan_id == claim.scan_id,
                WatchScanItem.provider_file_id == discovered.metadata.file_id,
            )
        )
        if row is None:
            row = WatchScanItem(
                watch_scan_id=claim.scan_id,
                provider_file_id=discovered.metadata.file_id,
                display_name=discovered.metadata.name,
                mime_type=discovered.metadata.mime_type,
                ancestor_folder_ids=list(discovered.ancestor_folder_ids),
                discovery_kind=discovery_kind,
                outcome=outcome,
            )
            session.add(row)
        row.watched_item_id = watched.id if watched is not None else None
        row.watch_document_version_id = version.id if version is not None else None
        row.sync_run_id = run_id
        row.provider_version = discovered.metadata.provider_version
        row.display_name = discovered.metadata.name
        row.mime_type = discovered.metadata.mime_type
        row.ancestor_folder_ids = list(discovered.ancestor_folder_ids)
        row.discovery_kind = discovery_kind
        row.outcome = outcome
        row.reason_code = reason_code
        row.matched_rule_id = rule_id
        row.matched_rule_version = rule_version
        return row


def google_factory(
    *,
    runtime: object,
    owner_subject: str,
    state_ttl_seconds: int,
    refresh_skew_seconds: int,
    baseline_max_attempts: int,
) -> GoogleFactory:
    from docrelay.integrations.google.runtime import GoogleRuntime

    if not isinstance(runtime, GoogleRuntime):
        raise TypeError("Google runtime is required for watch mode")

    def build(session: AsyncSession) -> GoogleConnectionService:
        return GoogleConnectionService(
            session=session,
            runtime=runtime,
            owner_subject=owner_subject,
            state_ttl_seconds=state_ttl_seconds,
            refresh_skew_seconds=refresh_skew_seconds,
            baseline_max_attempts=baseline_max_attempts,
        )

    return build


def build_watch_service(
    *,
    sessions: async_sessionmaker[AsyncSession],
    owner_subject: str,
    runtime: object,
    runs: SuperDocsWorkflow,
    state_ttl_seconds: int,
    refresh_skew_seconds: int,
    baseline_max_attempts: int,
    scan_lease_seconds: int,
    max_items_per_scan: int,
) -> WatchService:
    return WatchService(
        sessions=sessions,
        owner_subject=owner_subject,
        google_factory=google_factory(
            runtime=runtime,
            owner_subject=owner_subject,
            state_ttl_seconds=state_ttl_seconds,
            refresh_skew_seconds=refresh_skew_seconds,
            baseline_max_attempts=baseline_max_attempts,
        ),
        runs=runs,
        scan_lease_seconds=scan_lease_seconds,
        max_items_per_scan=max_items_per_scan,
    )


def _superdocs_baseline(registered: RegisteredBaseline) -> SuperDocsBaseline:
    result = registered.result
    return SuperDocsBaseline(
        cloud_document_id=registered.document.id,
        provider_revision_id=result.revision_id,
        source_format=registered.document.mime_type,
        captured_at=result.captured_at,
        native_raw_sha256=result.native_raw_sha256,
        native_canonical_sha256=result.native_canonical_sha256,
        exported_docx_sha256=result.exported_docx_sha256,
        canonical_schema_version=result.canonicalizer_version,
        capability_evidence=registered.capture.capability_evidence,
        provider_evidence=registered.capture.provider_evidence
        | {
            "watch_discovery_schema": WATCH_DISCOVERY_SCHEMA,
            "watch_capture_id": str(registered.capture.id),
        },
        docx_bytes=result.docx_bytes,
        filename=f"docrelay-source-{registered.document.id}.docx",
    )


def _resolve_rule(
    rules: tuple[ResolvedRule, ...], ancestor_folder_ids: tuple[str, ...]
) -> ResolvedRule | None:
    by_folder = {rule.folder_id: rule for rule in rules}
    for folder_id in reversed(ancestor_folder_ids):
        rule = by_folder.get(folder_id)
        if rule is not None:
            return rule
    return None


def _rule_snapshot(
    *,
    watch: WatchConfig,
    version_id: UUID,
    rule: ResolvedRule,
    ancestor_folder_ids: tuple[str, ...],
) -> dict[str, JsonValue]:
    return {
        "schema_version": WATCH_RULE_SCHEMA,
        "watch_config_id": str(watch.id),
        "watch_document_version_id": str(version_id),
        "root_folder_id": watch.parent_folder_id,
        "document_ancestor_folder_ids": list(ancestor_folder_ids),
        "resolution": "nearest_enabled_ancestor",
        "matched_folder_id": rule.folder_id,
        "rule_id": str(rule.rule_id),
        "rule_version": rule.version,
        "instruction": rule.instruction,
        "instruction_sha256": rule.instruction_sha256,
        "configuration": rule.configuration,
        "supported_formats": rule.supported_formats,
        "model_tier": None,
        "thinking_depth": None,
    }


async def _folder_path_to_root(
    provider: GoogleReadPort, *, root_id: str, folder_id: str
) -> tuple[tuple[str, ...], str]:
    reverse_path: list[str] = []
    seen: set[str] = set()
    current_id = folder_id
    folder_name = ""
    for _ in range(MAX_FOLDER_DEPTH):
        if current_id in seen:
            raise WatchRuleFolderInvalid("rule folder ancestry contains a cycle")
        seen.add(current_id)
        metadata = await provider.get_file(current_id)
        _validate_folder(metadata, expected_id=current_id, root=current_id == root_id)
        if not folder_name:
            folder_name = metadata.name
        reverse_path.append(current_id)
        if current_id == root_id:
            return tuple(reversed(reverse_path)), folder_name
        if len(metadata.parent_ids) != 1:
            raise WatchRuleFolderInvalid(
                "rule folder does not have one provable parent inside the watched root"
            )
        current_id = metadata.parent_ids[0]
    raise WatchRuleFolderInvalid("rule folder is not within the watched root")


async def _validate_document_path(
    provider: GoogleReadPort,
    *,
    root_id: str,
    ancestor_folder_ids: tuple[str, ...],
    metadata: GoogleFileMetadata,
) -> None:
    await _validate_folder_path(
        provider,
        root_id=root_id,
        ancestor_folder_ids=ancestor_folder_ids,
    )
    try:
        _validate_child(metadata, expected_parent_id=ancestor_folder_ids[-1])
    except WatchDiscoveryFailed as exc:
        raise WatchItemOutOfScope(
            "discovered Google document no longer belongs to the watched hierarchy"
        ) from exc
    if metadata.mime_type != GOOGLE_DOC_MIME:
        raise WatchDiscoveryFailed("discovered document changed to an unsupported type")


async def _validate_folder_path(
    provider: GoogleReadPort,
    *,
    root_id: str,
    ancestor_folder_ids: tuple[str, ...],
) -> None:
    if not ancestor_folder_ids or ancestor_folder_ids[0] != root_id:
        raise WatchDiscoveryFailed("discovered path escaped the watched root")
    previous: str | None = None
    for folder_id in ancestor_folder_ids:
        folder = await provider.get_file(folder_id)
        _validate_folder(folder, expected_id=folder_id, root=folder_id == root_id)
        if previous is not None and folder.parent_ids != (previous,):
            raise WatchDiscoveryFailed("watched folder moved outside the configured root")
        previous = folder_id


def _validate_folder(metadata: GoogleFileMetadata, *, expected_id: str, root: bool) -> None:
    error_type: type[WatchError] = WatchInvalidRoot if root else WatchRuleFolderInvalid
    if metadata.file_id != expected_id:
        raise error_type("Google Drive returned an unexpected folder identity")
    if metadata.mime_type != DRIVE_FOLDER_MIME:
        raise error_type("configured Google Drive item is not a folder")
    if metadata.trashed:
        raise error_type("configured Google Drive folder is trashed")
    if metadata.drive_id is not None:
        raise error_type("Shared Drive folders are not supported by watch mode")
    if "drive" not in metadata.spaces:
        raise error_type("configured folder is outside the supported My Drive space")
    if root and metadata.owned_by_me is not True:
        raise error_type("watched roots must be owned by the connected My Drive principal")


def _validate_child(metadata: GoogleFileMetadata, *, expected_parent_id: str) -> None:
    if metadata.trashed:
        raise WatchDiscoveryFailed("Google Drive returned a trashed child in an active listing")
    if metadata.drive_id is not None:
        raise WatchDiscoveryFailed("Shared Drive descendants are not supported")
    if "drive" not in metadata.spaces:
        raise WatchDiscoveryFailed("Google Drive child is outside the supported Drive space")
    if metadata.parent_ids != (expected_parent_id,):
        raise WatchDiscoveryFailed("Google Drive child did not prove the traversed parent")


def _authorization_state(metadata: GoogleFileMetadata) -> WriteAuthorizationState:
    return (
        WriteAuthorizationState.AUTHORIZED
        if metadata.is_app_authorized is True
        else WriteAuthorizationState.REQUIRED
    )


def _validate_interval(interval_seconds: int) -> None:
    if interval_seconds < 60 or interval_seconds > 86400:
        raise ValueError("watch interval must be between 60 seconds and 24 hours")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ClaimResult",
    "ExactFileAuthorizationMismatch",
    "WatchClaim",
    "WatchClaimLost",
    "WatchDiscoveryFailed",
    "WatchError",
    "WatchInvalidRoot",
    "WatchItemOutOfScope",
    "WatchNotFound",
    "WatchRuleFolderInvalid",
    "WatchService",
    "build_watch_service",
]
