from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from docrelay.api.dependencies import machine_operations
from docrelay.domain.enums import (
    WatchItemOutcome,
    WatchScanStatus,
    WatchScanTrigger,
    WriteAuthorizationState,
)
from docrelay.persistence.models import (
    FolderRule,
    WatchConfig,
    WatchedItem,
    WatchScan,
    WatchScanItem,
)
from docrelay.services.machine import RunSummary, ScanView
from docrelay.services.watch import WatchNotFound, WatchService

router = APIRouter(prefix="/api/v1/watches", tags=["watches"])


class WatchAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfigureWatchRequest(WatchAPIModel):
    connection_id: UUID
    root_folder_id: str = Field(min_length=1, max_length=255)
    interval_seconds: int = Field(default=300, ge=60, le=86400)
    enabled: bool = False

    @field_validator("root_folder_id")
    @classmethod
    def validate_root_folder_id(cls, value: str) -> str:
        return _opaque_file_id(value)


class ScheduleRequest(WatchAPIModel):
    enabled: bool
    interval_seconds: int = Field(ge=60, le=86400)


class ConfigureRuleRequest(WatchAPIModel):
    folder_id: str = Field(min_length=1, max_length=255)
    instruction: str = Field(min_length=1, max_length=20_000)
    enabled: bool = True

    @field_validator("folder_id")
    @classmethod
    def validate_folder_id(cls, value: str) -> str:
        return _opaque_file_id(value)


class WatchRootResponse(WatchAPIModel):
    watch_id: UUID
    connection_id: UUID
    root_folder_id: str
    root_name: str
    enabled: bool
    schedule: str
    interval_seconds: int
    timezone: str
    last_scan_at: datetime | None
    last_successful_scan_at: datetime | None
    next_scan_at: datetime | None
    last_scan_status: WatchScanStatus | None
    last_error_code: str | None


class WatchRootsResponse(WatchAPIModel):
    watches: tuple[WatchRootResponse, ...]


class RuleResponse(WatchAPIModel):
    rule_id: UUID
    watch_id: UUID
    folder_id: str
    folder_name: str
    version: int
    instruction: str
    instruction_sha256: str
    enabled: bool
    precedence: str = "nearest_enabled_ancestor"


class RulesResponse(WatchAPIModel):
    rules: tuple[RuleResponse, ...]


class ScanResponse(WatchAPIModel):
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


class ScansResponse(WatchAPIModel):
    scans: tuple[ScanResponse, ...]


class ScanItemResponse(WatchAPIModel):
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


class ScanItemsResponse(WatchAPIModel):
    items: tuple[ScanItemResponse, ...]


class WatchedItemResponse(WatchAPIModel):
    item_id: UUID
    provider_file_id: str
    provider_version: str
    name: str
    mime_type: str
    ancestor_folder_ids: tuple[str, ...]
    current_in_scope: bool
    last_seen_scan_id: UUID
    last_seen_at: datetime
    last_enqueued_revision_id: str | None
    run_id: UUID | None
    write_authorization_state: WriteAuthorizationState


class WatchedItemsResponse(WatchAPIModel):
    items: tuple[WatchedItemResponse, ...]


class RunSummariesResponse(WatchAPIModel):
    runs: tuple[RunSummary, ...]


def watch_service(request: Request) -> WatchService:
    return machine_operations(request).watch()


@router.post("", response_model=WatchRootResponse, status_code=status.HTTP_201_CREATED)
async def configure_watch(
    request: Request, payload: Annotated[ConfigureWatchRequest, Body()]
) -> WatchRootResponse:
    watch = await watch_service(request).configure_root(
        connection_id=payload.connection_id,
        root_folder_id=payload.root_folder_id,
        interval_seconds=payload.interval_seconds,
        enabled=payload.enabled,
    )
    return _watch_response(watch)


@router.get("", response_model=WatchRootsResponse)
async def list_watches(request: Request) -> WatchRootsResponse:
    watches = await watch_service(request).list_watches()
    return WatchRootsResponse(watches=tuple(_watch_response(watch) for watch in watches))


@router.get("/{watch_id}", response_model=WatchRootResponse)
async def get_watch(watch_id: UUID, request: Request) -> WatchRootResponse:
    return _watch_response(await watch_service(request).get_watch(watch_id))


@router.post("/{watch_id}/schedule", response_model=WatchRootResponse)
async def set_watch_schedule(
    watch_id: UUID,
    request: Request,
    payload: Annotated[ScheduleRequest, Body()],
) -> WatchRootResponse:
    watch = await watch_service(request).set_schedule(
        watch_id,
        enabled=payload.enabled,
        interval_seconds=payload.interval_seconds,
    )
    return _watch_response(watch)


@router.post("/{watch_id}/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def configure_watch_rule(
    watch_id: UUID,
    request: Request,
    payload: Annotated[ConfigureRuleRequest, Body()],
) -> RuleResponse:
    rule = await watch_service(request).configure_rule(
        watch_id,
        folder_id=payload.folder_id,
        instruction=payload.instruction,
        enabled=payload.enabled,
    )
    return _rule_response(rule)


@router.get("/{watch_id}/rules", response_model=RulesResponse)
async def list_watch_rules(watch_id: UUID, request: Request) -> RulesResponse:
    rules = await watch_service(request).list_rules(watch_id)
    return RulesResponse(rules=tuple(_rule_response(rule) for rule in rules))


@router.post("/{watch_id}/scans", response_model=ScanResponse)
async def trigger_watch_scan(watch_id: UUID, request: Request) -> ScanResponse:
    return _scan_response(await watch_service(request).trigger_manual(watch_id))


@router.get("/{watch_id}/scans", response_model=ScansResponse)
async def list_watch_scans(watch_id: UUID, request: Request) -> ScansResponse:
    scans = await watch_service(request).list_scans(watch_id)
    return ScansResponse(scans=tuple(_scan_response(scan) for scan in scans))


@router.get("/{watch_id}/scans/{scan_id}", response_model=ScanView)
async def get_watch_scan(watch_id: UUID, scan_id: UUID, request: Request) -> ScanView:
    view = await machine_operations(request).queries.get_scan(scan_id)
    if view.watch_id != watch_id:
        raise WatchNotFound("watch scan was not found under this root")
    return view


@router.get("/{watch_id}/scans/{scan_id}/runs", response_model=RunSummariesResponse)
async def list_watch_scan_runs(
    watch_id: UUID, scan_id: UUID, request: Request
) -> RunSummariesResponse:
    view = await machine_operations(request).queries.get_scan(scan_id)
    if view.watch_id != watch_id:
        raise WatchNotFound("watch scan was not found under this root")
    return RunSummariesResponse(runs=view.runs)


@router.get("/{watch_id}/scans/{scan_id}/items", response_model=ScanItemsResponse)
async def list_watch_scan_items(
    watch_id: UUID, scan_id: UUID, request: Request
) -> ScanItemsResponse:
    service = watch_service(request)
    scan = await service.get_scan(scan_id)
    if scan.watch_config_id != watch_id:
        raise WatchNotFound("watch scan was not found under this root")
    rows = await service.list_scan_items(scan_id)
    return ScanItemsResponse(items=tuple(_scan_item_response(row) for row in rows))


@router.get("/{watch_id}/items", response_model=WatchedItemsResponse)
async def list_watched_items(watch_id: UUID, request: Request) -> WatchedItemsResponse:
    rows = await watch_service(request).list_items(watch_id)
    return WatchedItemsResponse(items=tuple(_item_response(row) for row in rows))


@router.get("/{watch_id}/runs", response_model=RunSummariesResponse)
async def list_watch_runs(watch_id: UUID, request: Request) -> RunSummariesResponse:
    runs = await machine_operations(request).queries.list_watch_runs(watch_id)
    return RunSummariesResponse(runs=runs)


def _watch_response(watch: WatchConfig) -> WatchRootResponse:
    return WatchRootResponse(
        watch_id=watch.id,
        connection_id=watch.connection_id,
        root_folder_id=watch.parent_folder_id,
        root_name=watch.root_name,
        enabled=watch.enabled,
        schedule=watch.schedule,
        interval_seconds=watch.interval_seconds,
        timezone=watch.timezone,
        last_scan_at=watch.last_scan_at,
        last_successful_scan_at=watch.last_successful_scan_at,
        next_scan_at=watch.next_scan_at,
        last_scan_status=watch.last_scan_status,
        last_error_code=watch.last_error_code,
    )


def _rule_response(rule: FolderRule) -> RuleResponse:
    configured_name = rule.configuration.get("folder_name")
    return RuleResponse(
        rule_id=rule.id,
        watch_id=rule.watch_config_id,
        folder_id=rule.provider_folder_id,
        folder_name=(
            configured_name
            if isinstance(configured_name, str) and configured_name.strip()
            else rule.provider_folder_id
        ),
        version=rule.version,
        instruction=rule.instruction,
        instruction_sha256=rule.instruction_sha256,
        enabled=rule.active,
    )


def _scan_response(scan: WatchScan) -> ScanResponse:
    return ScanResponse(
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
    )


def _scan_item_response(row: WatchScanItem) -> ScanItemResponse:
    return ScanItemResponse(
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
    )


def _item_response(row: WatchedItem) -> WatchedItemResponse:
    return WatchedItemResponse(
        item_id=row.id,
        provider_file_id=row.provider_file_id,
        provider_version=row.provider_version,
        name=row.display_name,
        mime_type=row.mime_type,
        ancestor_folder_ids=tuple(row.ancestor_folder_ids),
        current_in_scope=row.current_in_scope,
        last_seen_scan_id=row.last_seen_scan_id,
        last_seen_at=row.last_seen_at,
        last_enqueued_revision_id=row.last_enqueued_revision_id,
        run_id=row.last_enqueued_run_id,
        write_authorization_state=row.write_authorization_state,
    )


def _opaque_file_id(value: str) -> str:
    if value != value.strip() or any(ord(character) < 33 for character in value):
        raise ValueError("Google file ID must be one opaque identifier")
    return value
