from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from docrelay.domain.write_plan import GoogleDocsBatchUpdate, Sha256


class GoogleContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoogleFileIdentity(GoogleContract):
    file_id: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = Field(min_length=1)
    drive_id: str | None = None
    mime_type: str = "application/vnd.google-apps.document"


class GoogleCapabilities(GoogleContract):
    can_edit: bool
    can_modify_content: bool
    can_download: bool
    can_copy: bool
    destination_can_add_children: bool
    restrictions: dict[str, JsonValue] = Field(default_factory=dict)


class ConsistentBaseline(GoogleContract):
    identity: GoogleFileIdentity
    revision_id: str = Field(min_length=1)
    native_raw_sha256: Sha256
    native_canonical_sha256: Sha256
    exported_docx_sha256: Sha256
    canonical_schema_version: str = Field(min_length=1)
    canonical_payload: dict[str, JsonValue]
    capability_evidence: dict[str, JsonValue]
    artifact_reference: str = Field(min_length=1)


class CurrentGoogleDocument(GoogleContract):
    identity: GoogleFileIdentity
    name: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    native_raw_sha256: Sha256
    canonical_schema_version: str = Field(min_length=1)
    canonical_sha256: Sha256
    canonical_payload: dict[str, JsonValue]
    capabilities: GoogleCapabilities
    safe_provider_metadata: dict[str, JsonValue] = Field(default_factory=dict)


class BackupReceipt(GoogleContract):
    backup_file_id: str = Field(min_length=1)
    parent_ids: tuple[str, ...] = Field(min_length=1)
    provider_metadata: dict[str, JsonValue]


class BackupVerification(GoogleContract):
    independently_readable: bool
    separate_file: bool
    expected_mime_type: bool
    expected_location: bool
    content_matches_baseline: bool
    acl_not_broader: bool
    canonical_sha256: Sha256
    evidence: dict[str, JsonValue]


class CommitClassification(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    CONFLICT = "CONFLICT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DEFINITELY_NOT_APPLIED = "DEFINITELY_NOT_APPLIED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class GuardedCommitResult(GoogleContract):
    classification: CommitClassification
    resulting_revision_id: str | None = None
    safe_provider_evidence: dict[str, JsonValue] = Field(default_factory=dict)


class CanonicalReread(GoogleContract):
    identity: GoogleFileIdentity
    revision_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    canonical_sha256: Sha256
    canonical_payload: dict[str, JsonValue]


class BaselineCapture(Protocol):
    async def capture_consistent_baseline(self, file_id: str) -> ConsistentBaseline: ...


class CommitCapabilityInspection(Protocol):
    async def inspect_commit_capabilities(
        self, file_id: str, destination_parent_id: str
    ) -> GoogleCapabilities: ...


class BackupCreation(Protocol):
    async def create_backup(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        backup_name: str,
        operation_metadata: dict[str, str],
    ) -> BackupReceipt: ...

    async def verify_backup(
        self,
        *,
        source_file_id: str,
        backup_file_id: str,
        expected_parent_id: str,
        expected_baseline_sha256: Sha256,
    ) -> BackupVerification: ...


class GuardedCommit(Protocol):
    """There is intentionally no unguarded provider-write method."""

    async def commit_guarded(
        self,
        *,
        file_id: str,
        operation: GoogleDocsBatchUpdate,
    ) -> GuardedCommitResult: ...


class CanonicalRead(Protocol):
    async def reread_canonical(self, file_id: str) -> CanonicalReread: ...


class GoogleWriteBackPort(Protocol):
    async def inspect_current(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> CurrentGoogleDocument: ...

    async def create_backup(
        self,
        *,
        file_id: str,
        destination_parent_id: str,
        backup_name: str,
        operation_metadata: dict[str, str],
    ) -> BackupReceipt: ...

    async def verify_backup(
        self,
        *,
        source_file_id: str,
        backup_file_id: str,
        expected_parent_id: str,
        expected_baseline_sha256: Sha256,
    ) -> BackupVerification: ...

    async def commit_guarded(
        self,
        *,
        file_id: str,
        operation: GoogleDocsBatchUpdate,
        watched_root_id: str | None = None,
        watched_ancestor_folder_ids: tuple[str, ...] = (),
    ) -> GuardedCommitResult: ...
