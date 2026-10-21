"""SQLAlchemy models for screenplay formatting"""
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, Index, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from backend.models.base import Base, TimestampMixin, UUIDMixin


class ScreenplayFormattingItem(Base, UUIDMixin, TimestampMixin):
    """
    Screenplay formatting item.

    Represents one formatting suggestion for one screenplay element.
    Each item can be individually approved or rejected during review.
    """
    __tablename__ = "screenplay_formatting_items"

    # Foreign keys
    workflow_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True
    )
    review_id = Column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id"),
        nullable=True,  # Nullable until diff stage creates review
        index=True
    )

    # Element metadata
    element_index = Column(Integer, nullable=False)  # Order in screenplay
    element_type = Column(String, nullable=False)  # scene_heading, action, character, dialogue, parenthetical, transition, uncertain
    scene_number = Column(Integer, nullable=True)  # Scene number if applicable
    character_name = Column(String, nullable=True)  # Character name for dialogue/character lines

    # Text content
    original_text = Column(Text, nullable=False)  # Original text from input
    formatted_text = Column(Text, nullable=False)  # Formatted text

    # Change metadata
    change_type = Column(String, nullable=False)  # capitalization, spacing, indentation, no_change, uncertain
    reason = Column(Text, nullable=True)  # Explanation for formatting change
    diff_tokens = Column(JSON, nullable=True)  # Token-level diff for UI display
    content_drift = Column(Boolean, default=False, nullable=False)  # Whether AI changed meaning

    # Review state
    status = Column(String, nullable=False, default="pending")  # pending, approved, rejected
    reviewer_comment = Column(Text, nullable=True)  # Comment from reviewer if rejected
    confidence_score = Column(Float, nullable=True)  # AI confidence score if applicable

    # Relationships
    workflow_run = relationship("WorkflowRun", foreign_keys=[workflow_run_id])
    review = relationship("Review", foreign_keys=[review_id])

    # Composite indexes for performance
    __table_args__ = (
        Index("ix_screenplay_run_element_idx", "workflow_run_id", "element_index"),
        Index("ix_screenplay_review_status", "review_id", "status"),
    )
