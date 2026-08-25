from sqlalchemy import Column, String, Float, Boolean, Integer, ForeignKey, JSON, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from backend.models.base import TimestampMixin, UUIDMixin
from backend.database import Base


class QualityGateConfig(Base, UUIDMixin, TimestampMixin):
    """Configuration for quality gate checks on a workspace."""
    __tablename__ = "quality_gate_configs"

    workspace_id = Column(PG_UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True)
    block_on_failure = Column(Boolean, nullable=False, default=False)
    checks_config = Column(JSON, nullable=False, default=dict)

    workspace = relationship("Workspace")
    results = relationship("QualityGateResult", back_populates="config")


class QualityGateResult(Base, UUIDMixin, TimestampMixin):
    """Result of running quality gate checks on a workflow run."""
    __tablename__ = "quality_gate_results"

    workflow_run_id = Column(PG_UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True)
    config_id = Column(PG_UUID(as_uuid=True), ForeignKey("quality_gate_configs.id"), nullable=True)
    status = Column(String, nullable=False)  # passed, failed, warning, skipped
    checks_run = Column(Integer, nullable=False, default=0)
    checks_passed = Column(Integer, nullable=False, default=0)
    checks_failed = Column(Integer, nullable=False, default=0)
    blocking = Column(Boolean, nullable=False, default=False)
    details = Column(JSON, nullable=False, default=list)

    workflow_run = relationship("WorkflowRun")
    config = relationship("QualityGateConfig", back_populates="results")

    __table_args__ = (
        Index("ix_qg_results_run", "workflow_run_id"),
    )
