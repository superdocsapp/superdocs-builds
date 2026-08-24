from enum import StrEnum


class Provider(StrEnum):
    GOOGLE = "GOOGLE"


class ConnectionStatus(StrEnum):
    PENDING = "PENDING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    INVALID = "INVALID"


class SyncMode(StrEnum):
    PREVIEW = "PREVIEW"
    COMMIT = "COMMIT"


class SyncRunState(StrEnum):
    QUEUED = "QUEUED"
    BASELINING = "BASELINING"
    EDITING = "EDITING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    REVIEWED_EXPORT_READY = "REVIEWED_EXPORT_READY"
    READY_TO_COMMIT = "READY_TO_COMMIT"
    PREVIEW_READY = "PREVIEW_READY"
    COMMITTING = "COMMITTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"
    COMMIT_OUTCOME_UNKNOWN = "COMMIT_OUTCOME_UNKNOWN"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EffectType(StrEnum):
    SUPERDOCS_UPLOAD = "SUPERDOCS_UPLOAD"
    SUPERDOCS_JOB_START = "SUPERDOCS_JOB_START"
    SUPERDOCS_REVIEW_SUBMISSION = "SUPERDOCS_REVIEW_SUBMISSION"
    SUPERDOCS_CONTINUE = "SUPERDOCS_CONTINUE"
    SUPERDOCS_FOCUS = "SUPERDOCS_FOCUS"
    GOOGLE_BACKUP_COPY = "GOOGLE_BACKUP_COPY"
    GOOGLE_BATCH_UPDATE = "GOOGLE_BATCH_UPDATE"


class EffectOutcome(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN = "UNKNOWN"


class ReviewAwaitingKind(StrEnum):
    CHANGE_BATCH = "CHANGE_BATCH"
    CONTINUE_PROMPT = "CONTINUE_PROMPT"


class ReviewRoundResolution(StrEnum):
    SUBMIT_CHANGES = "SUBMIT_CHANGES"
    CONTINUE = "CONTINUE"
    STOP = "STOP"


class ChangeDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class BackupStatus(StrEnum):
    PLANNED = "PLANNED"
    CREATED = "CREATED"
    VERIFIED = "VERIFIED"
    ORPHANED = "ORPHANED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ConflictChoice(StrEnum):
    CANCEL = "CANCEL"
    REVIEW_LATEST = "REVIEW_LATEST"


class OperationStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SuperDocsDocumentRole(StrEnum):
    TARGET = "TARGET"
    REFERENCE = "REFERENCE"


class SuperDocsJobStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProposalOperation(StrEnum):
    EDIT = "edit"
    CREATE = "create"
    DELETE = "delete"


class WatchScanStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class WatchScanTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"


class WatchItemOutcome(StrEnum):
    ENQUEUED = "ENQUEUED"
    UNCHANGED = "UNCHANGED"
    NO_RULE = "NO_RULE"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class WatchVersionStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    NO_RULE = "NO_RULE"
    ENQUEUE_PENDING = "ENQUEUE_PENDING"
    ENQUEUED = "ENQUEUED"
    FAILED = "FAILED"


class WriteAuthorizationState(StrEnum):
    REQUIRED = "REQUIRED"
    AUTHORIZED = "AUTHORIZED"
