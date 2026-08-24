from datetime import datetime
from enum import Enum as PythonEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from docrelay.domain.enums import (
    BackupStatus,
    ChangeDecision,
    ConflictChoice,
    ConnectionStatus,
    EffectOutcome,
    EffectType,
    OperationStatus,
    ProposalOperation,
    Provider,
    ReviewAwaitingKind,
    ReviewRoundResolution,
    SuperDocsDocumentRole,
    SuperDocsJobStatus,
    SyncMode,
    SyncRunState,
    VerificationStatus,
    WatchItemOutcome,
    WatchScanStatus,
    WatchScanTrigger,
    WatchVersionStatus,
    WriteAuthorizationState,
)
from docrelay.persistence.base import Base

JsonObject = dict[str, Any]
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def enum_type(enum_class: type[PythonEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


class IdMixin:
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CloudConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "cloud_connections"
    __table_args__ = (
        UniqueConstraint(
            "owner_subject",
            "provider",
            "provider_account_subject",
            name="uq_cloud_connection_owner_provider_account",
        ),
    )

    owner_subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[Provider] = mapped_column(
        enum_type(Provider, "provider"), nullable=False, default=Provider.GOOGLE
    )
    provider_account_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ConnectionStatus] = mapped_column(
        enum_type(ConnectionStatus, "connection_status"),
        nullable=False,
        default=ConnectionStatus.PENDING,
    )
    granted_scopes: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    credential_reference: Mapped[str | None] = mapped_column(String(512))
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_reason: Mapped[str | None] = mapped_column(String(128))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (UniqueConstraint("connection_id", name="uq_oauth_credential_connection"),)

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoogleOAuthState(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "google_oauth_states"

    owner_subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    browser_nonce_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_scopes: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CloudDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "cloud_documents"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "provider_file_id", name="uq_cloud_document_connection_file"
        ),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_connections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(512))
    parent_ids: Mapped[list[str]] = mapped_column(
        JSON_TYPE, nullable=False, default=list, server_default=text("'[]'")
    )
    drive_id: Mapped[str | None] = mapped_column(String(255))
    last_seen_revision_id: Mapped[str | None] = mapped_column(Text)
    last_successful_revision_id: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_metadata: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )


class WatchConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "watch_configs"
    __table_args__ = (
        UniqueConstraint("connection_id", "parent_folder_id", name="uq_watch_connection_parent"),
        CheckConstraint(
            "interval_seconds >= 60 AND interval_seconds <= 86400",
            name="watch_interval_bounds",
        ),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    root_name: Mapped[str] = mapped_column(
        String(512), nullable=False, default="Google Drive folder"
    )
    schedule: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    default_mode: Mapped[SyncMode] = mapped_column(
        enum_type(SyncMode, "sync_mode"), nullable=False, default=SyncMode.PREVIEW
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_scan_status: Mapped[WatchScanStatus | None] = mapped_column(
        enum_type(WatchScanStatus, "watch_scan_status")
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128))


class WatchScan(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "watch_scans"
    __table_args__ = (
        UniqueConstraint("watch_config_id", "active_key", name="uq_watch_scan_active"),
        CheckConstraint("active_key IS NULL OR active_key = 'ACTIVE'", name="active_key_valid"),
        CheckConstraint("claim_generation >= 1", name="watch_claim_generation_positive"),
    )

    watch_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[WatchScanTrigger] = mapped_column(
        enum_type(WatchScanTrigger, "watch_scan_trigger"), nullable=False
    )
    status: Mapped[WatchScanStatus] = mapped_column(
        enum_type(WatchScanStatus, "watch_scan_status"),
        nullable=False,
        default=WatchScanStatus.RUNNING,
        index=True,
    )
    active_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lease_token: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    claim_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enqueued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_detail: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)


class FolderRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "folder_rules"
    __table_args__ = (
        UniqueConstraint(
            "watch_config_id",
            "provider_folder_id",
            "version",
            name="uq_folder_rule_watch_folder_version",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    watch_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    instruction_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    supported_formats: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WatchCursor(IdMixin, TimestampMixin, Base):
    __tablename__ = "watch_cursors"
    __table_args__ = (UniqueConstraint("watch_config_id", name="uq_watch_cursor_config"),)

    watch_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_configs.id", ondelete="CASCADE"), nullable=False
    )
    cursor: Mapped[str] = mapped_column(Text, nullable=False)
    cursor_metadata: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WatchedItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "watched_items"
    __table_args__ = (
        UniqueConstraint("watch_config_id", "provider_file_id", name="uq_watched_item_watch_file"),
    )

    watch_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cloud_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cloud_documents.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ancestor_folder_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    current_in_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_scan_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_scans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_enqueued_provider_version: Mapped[str | None] = mapped_column(String(128))
    last_enqueued_revision_id: Mapped[str | None] = mapped_column(Text)
    last_enqueued_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    write_authorization_state: Mapped[WriteAuthorizationState] = mapped_column(
        enum_type(WriteAuthorizationState, "write_authorization_state"),
        nullable=False,
        default=WriteAuthorizationState.REQUIRED,
    )
    write_authorization_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchDocumentVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "watch_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "watched_item_id", "provider_version", name="uq_watch_document_item_version"
        ),
        UniqueConstraint("sync_run_id", name="uq_watch_document_version_run"),
    )

    watched_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("watched_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_seen_scan_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_scans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[WatchVersionStatus] = mapped_column(
        enum_type(WatchVersionStatus, "watch_version_status"), nullable=False
    )
    provider_revision_id: Mapped[str | None] = mapped_column(Text)
    folder_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folder_rules.id", ondelete="RESTRICT"), nullable=True
    )
    folder_rule_version: Mapped[int | None] = mapped_column(Integer)
    rule_snapshot: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)
    sync_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_detail: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)


class WatchScanItem(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "watch_scan_items"
    __table_args__ = (
        UniqueConstraint("watch_scan_id", "provider_file_id", name="uq_watch_scan_item_file"),
    )

    watch_scan_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    watched_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("watched_items.id", ondelete="SET NULL"), nullable=True
    )
    watch_document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("watch_document_versions.id", ondelete="SET NULL"), nullable=True
    )
    sync_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="SET NULL"), nullable=True
    )
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    ancestor_folder_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    discovery_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[WatchItemOutcome] = mapped_column(
        enum_type(WatchItemOutcome, "watch_item_outcome"), nullable=False
    )
    reason_code: Mapped[str | None] = mapped_column(String(128))
    matched_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folder_rules.id", ondelete="RESTRICT"), nullable=True
    )
    matched_rule_version: Mapped[int | None] = mapped_column(Integer)


class WatchRunLink(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "watch_run_links"
    __table_args__ = (
        UniqueConstraint("watch_document_version_id", name="uq_watch_run_link_version"),
        UniqueConstraint("sync_run_id", name="uq_watch_run_link_run"),
    )

    watch_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_configs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    watch_scan_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_scans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    watched_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("watched_items.id", ondelete="RESTRICT"), nullable=False
    )
    watch_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("watch_document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    folder_rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("folder_rules.id", ondelete="RESTRICT"), nullable=False
    )
    folder_rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_snapshot: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    write_authorization_state: Mapped[WriteAuthorizationState] = mapped_column(
        enum_type(WriteAuthorizationState, "write_authorization_state"), nullable=False
    )
    write_authorization_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    write_authorization_evidence: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )


class SyncRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        UniqueConstraint("intent_key", name="uq_sync_run_intent_key"),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
    )

    cloud_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    folder_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("folder_rules.id", ondelete="RESTRICT"), nullable=True
    )
    folder_rule_version: Mapped[int | None] = mapped_column(Integer)
    rule_snapshot: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    mode: Mapped[SyncMode] = mapped_column(enum_type(SyncMode, "sync_mode"), nullable=False)
    state: Mapped[SyncRunState] = mapped_column(
        enum_type(SyncRunState, "sync_run_state"),
        nullable=False,
        default=SyncRunState.QUEUED,
        index=True,
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    intent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_revision_id: Mapped[str | None] = mapped_column(Text)
    precommit_revision_id: Mapped[str | None] = mapped_column(Text)
    resulting_revision_id: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_detail: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceSnapshot(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (UniqueConstraint("sync_run_id", name="uq_source_snapshot_run"),)

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False
    )
    cloud_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_format: Mapped[str] = mapped_column(String(255), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    native_raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    native_canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exported_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_reference: Mapped[str | None] = mapped_column(String(512))
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    provider_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class GoogleBaselineCapture(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "google_baseline_captures"
    __table_args__ = (
        CheckConstraint("attempt_count >= 1", name="google_baseline_attempt_positive"),
    )

    cloud_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("cloud_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    native_raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    native_canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exported_docx_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    exported_docx_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonicalizer_version: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_payload: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    capability_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    parent_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    capture_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class RunTransition(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "run_transitions"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "sequence", name="uq_run_transition_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[SyncRunState | None] = mapped_column(
        enum_type(SyncRunState, "sync_run_from_state")
    )
    to_state: Mapped[SyncRunState] = mapped_column(
        enum_type(SyncRunState, "sync_run_to_state"), nullable=False
    )
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    evidence: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )


class RunOperation(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "run_operations"

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[OperationStatus] = mapped_column(
        enum_type(OperationStatus, "operation_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    provider_operation_count: Mapped[int | None] = mapped_column(Integer)
    safe_metrics: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    error: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)


class SuperDocsSession(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "superdocs_sessions"
    __table_args__ = (
        UniqueConstraint("sync_run_id", name="uq_superdocs_session_run"),
        UniqueConstraint("session_id", name="uq_superdocs_session_external_id"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    raw_evidence: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )


class SuperDocsDocument(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "superdocs_documents"
    __table_args__ = (
        UniqueConstraint(
            "superdocs_session_id",
            "session_document_id",
            name="uq_superdocs_document_session_local_id",
        ),
    )

    superdocs_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[SuperDocsDocumentRole] = mapped_column(
        enum_type(SuperDocsDocumentRole, "superdocs_document_role"), nullable=False
    )
    session_document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    durable_document_id: Mapped[str | None] = mapped_column(String(255))
    upload_version_id: Mapped[str | None] = mapped_column(String(255))
    final_version_id: Mapped[str | None] = mapped_column(String(255))
    baseline_html_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class SuperDocsJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "superdocs_jobs"
    __table_args__ = (
        UniqueConstraint(
            "superdocs_session_id", "provider_job_id", name="uq_superdocs_job_session_external_id"
        ),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    superdocs_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_sessions.id", ondelete="CASCADE"), nullable=False
    )
    target_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_documents.id", ondelete="RESTRICT"), nullable=False
    )
    provider_job_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SuperDocsJobStatus] = mapped_column(
        enum_type(SuperDocsJobStatus, "superdocs_job_status"), nullable=False
    )
    start_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_state: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    usage_evidence: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SuperDocsExport(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "superdocs_exports"
    __table_args__ = (
        UniqueConstraint("superdocs_job_id", name="uq_superdocs_export_job"),
        UniqueConstraint("artifact_reference", name="uq_superdocs_export_artifact_reference"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    superdocs_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    superdocs_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_documents.id", ondelete="RESTRICT"), nullable=False
    )
    superdocs_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_disposition: Mapped[str | None] = mapped_column(String(1024))
    warnings_raw: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[JsonObject]] = mapped_column(
        JSON_TYPE, nullable=False, default=list, server_default=text("'[]'")
    )
    final_version_id: Mapped[str | None] = mapped_column(String(255))
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRound(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_rounds"
    __table_args__ = (
        UniqueConstraint("superdocs_job_id", "ordinal", name="uq_review_round_job_ordinal"),
        CheckConstraint("ordinal >= 1", name="ordinal_positive"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    superdocs_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_jobs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    awaiting_kind: Mapped[ReviewAwaitingKind] = mapped_column(
        enum_type(ReviewAwaitingKind, "review_awaiting_kind"), nullable=False
    )
    raw_pending_evidence: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    resolution: Mapped[ReviewRoundResolution | None] = mapped_column(
        enum_type(ReviewRoundResolution, "review_round_resolution")
    )
    resolved_by_subject: Mapped[str | None] = mapped_column(String(255))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_evidence: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)


class ProposedChange(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "proposed_changes"
    __table_args__ = (
        UniqueConstraint(
            "superdocs_job_id",
            "superdocs_change_id",
            name="uq_proposed_change_job_external_id",
        ),
        UniqueConstraint("review_round_id", "ordinal", name="uq_proposed_change_round_ordinal"),
        CheckConstraint("ordinal IS NULL OR ordinal >= 1", name="ordinal_positive"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    superdocs_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_jobs.id", ondelete="CASCADE"), nullable=False
    )
    review_round_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False
    )
    target_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("superdocs_documents.id", ondelete="RESTRICT"), nullable=False
    )
    replaces_proposal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proposed_changes.id", ondelete="RESTRICT")
    )
    superdocs_change_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[ProposalOperation] = mapped_column(
        enum_type(ProposalOperation, "proposal_operation"), nullable=False
    )
    chunk_id: Mapped[str | None] = mapped_column(String(255))
    old_html: Mapped[str | None] = mapped_column(Text)
    new_html: Mapped[str | None] = mapped_column(Text)
    ai_explanation: Mapped[str | None] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class ReviewDecision(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "review_decisions"
    __table_args__ = (UniqueConstraint("proposed_change_id", name="uq_review_decision_proposal"),)

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposed_change_id: Mapped[UUID] = mapped_column(
        ForeignKey("proposed_changes.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[ChangeDecision] = mapped_column(
        enum_type(ChangeDecision, "change_decision"), nullable=False
    )
    reviewer_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text)
    decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class MappingProof(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "mapping_proofs"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "integrity_sha256", name="uq_mapping_proof_run_integrity"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(128), nullable=False)
    integrity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_payload: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class WritePlan(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "write_plans"
    __table_args__ = (
        UniqueConstraint("sync_run_id", name="uq_write_plan_run"),
        UniqueConstraint("integrity_sha256", name="uq_write_plan_integrity"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False
    )
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    mapping_proof_id: Mapped[UUID] = mapped_column(
        ForeignKey("mapping_proofs.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    mapper_version: Mapped[str] = mapped_column(String(128), nullable=False)
    verifier_version: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_operations: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    expected_postimage_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    integrity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WritePlanLineage(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "write_plan_lineage"
    __table_args__ = (
        UniqueConstraint(
            "write_plan_id", "proposed_change_id", name="uq_write_plan_lineage_proposal"
        ),
    )

    write_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("write_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposed_change_id: Mapped[UUID] = mapped_column(
        ForeignKey("proposed_changes.id", ondelete="RESTRICT"), nullable=False
    )
    review_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class ExternalEffect(IdMixin, TimestampMixin, Base):
    __tablename__ = "external_effects"
    __table_args__ = (
        UniqueConstraint("sync_run_id", "effect_key", name="uq_external_effect_run_key"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
    )

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effect_key: Mapped[str] = mapped_column(String(255), nullable=False)
    effect_type: Mapped[EffectType] = mapped_column(
        enum_type(EffectType, "effect_type"), nullable=False
    )
    outcome: Mapped[EffectOutcome] = mapped_column(
        enum_type(EffectOutcome, "effect_outcome"),
        nullable=False,
        default=EffectOutcome.NOT_STARTED,
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_metadata: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)
    provider_external_id: Mapped[str | None] = mapped_column(String(512))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)
    reconciliation_evidence: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)


class Backup(IdMixin, TimestampMixin, Base):
    __tablename__ = "backups"
    __table_args__ = (UniqueConstraint("external_effect_id", name="uq_backup_external_effect"),)

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    write_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("write_plans.id", ondelete="RESTRICT"), nullable=False
    )
    external_effect_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_effects.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[BackupStatus] = mapped_column(
        enum_type(BackupStatus, "backup_status"), nullable=False, default=BackupStatus.PLANNED
    )
    provider_backup_file_id: Mapped[str | None] = mapped_column(String(255))
    baseline_revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_sha256: Mapped[str | None] = mapped_column(String(64))
    location_evidence: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)
    acl_evidence: Mapped[JsonObject | None] = mapped_column(JSON_TYPE)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WriteConflict(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "write_conflicts"
    __table_args__ = (UniqueConstraint("sync_run_id", name="uq_write_conflict_run"),)

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    write_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("write_plans.id", ondelete="RESTRICT"), nullable=False
    )
    backup_id: Mapped[UUID | None] = mapped_column(ForeignKey("backups.id", ondelete="RESTRICT"))
    baseline_revision_id: Mapped[str] = mapped_column(Text, nullable=False)
    latest_revision_id: Mapped[str | None] = mapped_column(Text)
    detection_stage: Mapped[str] = mapped_column(String(128), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    safe_evidence: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )
    decision: Mapped[ConflictChoice | None] = mapped_column(
        enum_type(ConflictChoice, "conflict_choice")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_subject: Mapped[str | None] = mapped_column(String(255))


class VerificationResult(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "verification_results"

    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    write_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("write_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, "verification_status"), nullable=False
    )
    verifier_version: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_canonical_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actual_canonical_sha256: Mapped[str | None] = mapped_column(String(64))
    actual_revision_id: Mapped[str | None] = mapped_column(Text)
    report: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False)


class AuditEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_events"

    sync_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="SET NULL"), index=True
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cloud_connections.id", ondelete="SET NULL"), index=True
    )
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    safe_payload: Mapped[JsonObject] = mapped_column(
        JSON_TYPE, nullable=False, default=dict, server_default=text("'{}'")
    )


Index(
    "ix_sync_runs_document_nonterminal",
    SyncRun.cloud_document_id,
    SyncRun.state,
)
Index("ix_watch_configs_due", WatchConfig.enabled, WatchConfig.next_scan_at)
Index("ix_watched_items_scope", WatchedItem.watch_config_id, WatchedItem.current_in_scope)
Index(
    "ix_watch_document_versions_status",
    WatchDocumentVersion.watched_item_id,
    WatchDocumentVersion.status,
)
Index("ix_audit_events_type_created", AuditEvent.event_type, AuditEvent.created_at)
Index("ix_run_operations_run_stage", RunOperation.sync_run_id, RunOperation.stage)
Index(
    "ix_google_baseline_document_revision",
    GoogleBaselineCapture.cloud_document_id,
    GoogleBaselineCapture.provider_revision_id,
)


__all__ = [
    "AuditEvent",
    "Backup",
    "CloudConnection",
    "CloudDocument",
    "ExternalEffect",
    "FolderRule",
    "GoogleBaselineCapture",
    "GoogleOAuthState",
    "MappingProof",
    "OAuthCredential",
    "ProposedChange",
    "ReviewDecision",
    "ReviewRound",
    "RunOperation",
    "RunTransition",
    "SourceSnapshot",
    "SuperDocsDocument",
    "SuperDocsExport",
    "SuperDocsJob",
    "SuperDocsSession",
    "SyncRun",
    "VerificationResult",
    "WatchConfig",
    "WatchCursor",
    "WatchDocumentVersion",
    "WatchRunLink",
    "WatchScan",
    "WatchScanItem",
    "WatchedItem",
    "WriteConflict",
    "WritePlan",
    "WritePlanLineage",
]
