"""
@file: backend/models/run.py
@description: The Run entity: one end-to-end digest job, its status, and the checkpoint blob
    that lets it survive a process kill.
@flow: created by graph.create_run() -> mutated through the checkpoint store by every node
    -> read by the API and MCP layers.
@dependencies:
    - backend.models.base: declarative Base, shared enums, portable column types
    - sqlalchemy.orm: Mapped / mapped_column / relationship
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import (
    Base,
    JSONType,
    RunStatus,
    UUIDType,
    utcnow,
)

if TYPE_CHECKING:
    from backend.models.approval import ApprovalItem
    from backend.models.conversation import Conversation
    from backend.models.theme import Theme

class Run(Base):
    """One end-to-end digest job.

    checkpoint_data holds the serialised LangGraph state after each completed stage.
    That single JSONB column is what makes the run survive a process kill: on restart
    the graph reads it, skips finished stages, and re-enters at current_stage.
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"),
        default=RunStatus.PENDING,
        nullable=False,
        index=True,
    )
    current_stage: Mapped[str | None] = mapped_column(String(64))
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    input_path: Mapped[str] = mapped_column(Text, nullable=False)
    last_digest_path: Mapped[str | None] = mapped_column(Text)

    quarter_label: Mapped[str] = mapped_column(String(32), default="Q3 2026")

    # SuperDocs is session-centric: session_id is a string we choose and reuse across
    # every turn. document_id is the durable Files id we get back after upload.
    superdocs_session_id: Mapped[str | None] = mapped_column(String(256), index=True)
    superdocs_document_id: Mapped[str | None] = mapped_column(String(128))
    superdocs_job_id: Mapped[str | None] = mapped_column(String(128))

    checkpoint_data: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    cost_report: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    decision_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONType, default=list, nullable=False
    )

    error_message: Mapped[str | None] = mapped_column(Text)
    export_path: Mapped[str | None] = mapped_column(Text)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    themes: Mapped[list["Theme"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    approval_items: Mapped[list["ApprovalItem"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    @property
    def is_resumable(self) -> bool:
        return self.status in {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.PAUSED,
            RunStatus.FAILED,
        }

    @property
    def is_terminal(self) -> bool:
        return self.status in {RunStatus.COMPLETE, RunStatus.FAILED}
