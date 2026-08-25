from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, JSON, Text, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, UUIDMixin, TimestampMixin


class Workflow(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflows"

    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    configuration_schema = Column(JSON, nullable=True)
    current_version = Column(String, default="1.0.0", nullable=False)

    # Relationships
    runs = relationship("WorkflowRun", back_populates="workflow")


class WorkflowRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_runs"

    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False, index=True)
    template_id = Column(UUID(as_uuid=True), nullable=True)
    template_version = Column(String, nullable=True)
    status = Column(String, default="queued", nullable=False)
    current_stage = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    workflow_version = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    version_number = Column(Integer, default=1, nullable=False)

    # Focused update support (Phase 7)
    is_focused_update = Column(Boolean, nullable=False, default=False)
    baseline_run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    workspace = relationship("Workspace", back_populates="workflow_runs")
    workflow = relationship("Workflow", back_populates="runs")
    stages = relationship("WorkflowStage", back_populates="run", cascade="all, delete-orphan")
    claims = relationship("Claim", back_populates="workflow_run")
    reviews = relationship("Review", back_populates="workflow_run")
    superdocs_session = relationship("SuperDocsSession", back_populates="workflow_run", uselist=False)
    memo_sections = relationship("MemoSection", back_populates="workflow_run", cascade="all, delete-orphan")


class WorkflowStage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_stages"

    run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    stage_name = Column(String, nullable=False)
    status = Column(String, default="queued", nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    input_hash = Column(String, nullable=True)
    checkpoint_data = Column(JSON, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Agentic decision tracking (Phase 7)
    decision_type = Column(String(50), nullable=True)
    decision_reason = Column(Text, nullable=True)
    decision_metadata = Column(JSON, nullable=True)

    # Relationships
    run = relationship("WorkflowRun", back_populates="stages")
    logs = relationship("WorkflowStageLog", back_populates="stage", cascade="all, delete-orphan")


class WorkflowStageLog(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_stage_logs"

    run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("workflow_stages.id"), nullable=False, index=True)
    stage_name = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=True)
    logged_at = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    stage = relationship("WorkflowStage", back_populates="logs")
