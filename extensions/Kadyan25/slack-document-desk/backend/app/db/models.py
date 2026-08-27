import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SuperdocsSession(Base):
    """One SuperDocs session per Slack user. session_id = f"slack-user-{slack_user_id}"."""

    __tablename__ = "superdocs_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    superdocs_session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class DocumentLink(Base):
    """Which SuperDocs documents a Slack user has open — cached for fast Home tab rendering."""

    __tablename__ = "document_links"
    __table_args__ = (UniqueConstraint("slack_user_id", "superdocs_document_id", name="uq_document_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    superdocs_document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    # Each shared file gets its OWN SuperDocs session — uploading into a session
    # that already holds a document overwrites it in place (SuperDocs behavior),
    # so a per-document session is what keeps shares from clobbering each other.
    # Nullable only for links created before this column existed.
    superdocs_session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    is_focused: Mapped[bool] = mapped_column(default=False)
    last_synced_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class PendingJob(Base):
    """Local cache of in-flight/awaiting-approval SuperDocs jobs. SuperDocs itself stays the source of truth."""

    __tablename__ = "pending_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    superdocs_session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    superdocs_document_id: Mapped[str] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    pending_changes_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc),
    )


class ProcessedChange(Base):
    """Claimed via INSERT ... ON CONFLICT DO NOTHING before ever calling approve_change —
    a Slack retry firing the same button click twice must not double-apply. DB-level
    uniqueness, not an app-level check-then-write (same pattern as Task 1's concurrency fix)."""

    __tablename__ = "processed_changes"
    __table_args__ = (UniqueConstraint("job_id", "change_id", name="uq_processed_change"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(256), nullable=False)
    change_id: Mapped[str] = mapped_column(String(256), nullable=False)
    approved: Mapped[bool] = mapped_column(nullable=False)
    decided_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class ProcessedSlackEvent(Base):
    """Claimed via INSERT ... ON CONFLICT DO NOTHING before any event handler does real
    work — Slack retries an Events API delivery (same event_id every time) whenever our
    ack takes longer than ~3s, and file_shared/app_mention's real work (a SuperDocs
    upload or chat_async call) routinely does. Without this, a single share or mention
    can fire the handler 2-3x, each producing its own duplicate upload/job and ack
    message — found live (see issues.md), same failure class approve/reject's
    ProcessedChange table already guards against."""

    __tablename__ = "processed_slack_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class RecentOutput(Base):
    """Last completed exports per Slack user — re-exported on demand once the signed URL's TTL passes."""

    __tablename__ = "recent_output"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str] = mapped_column(String(256), ForeignKey("pending_jobs.job_id"), nullable=True)
    superdocs_session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    superdocs_document_id: Mapped[str] = mapped_column(String(256), nullable=False)
    export_format: Mapped[str] = mapped_column(String(16), nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
