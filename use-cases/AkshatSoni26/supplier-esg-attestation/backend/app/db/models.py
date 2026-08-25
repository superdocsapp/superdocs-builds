import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, Boolean, Text, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupplierModel(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)  # TIER_1_STRATEGIC, TIER_2_MANUFACTURING, TIER_3_COMMODITY
    region: Mapped[str] = mapped_column(String(32), nullable=False)  # EU, NORTH_AMERICA, APAC, GLOBAL
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    attestations = relationship("AttestationCycleModel", back_populates="supplier", cascade="all, delete-orphan")


class AttestationCycleModel(Base):
    __tablename__ = "attestation_cycles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    cycle_year: Mapped[int] = mapped_column(Integer, default=2026)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)  # DRAFT, ISSUED, SUBMITTED, NORMALIZED, UNDER_REVIEW, APPROVED, FOLLOW_UP_REQUIRED
    issued_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issued_document_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    response_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    response_format: Mapped[str | None] = mapped_column(String(32), nullable=True)  # PDF, DOCX, TXT, JSON
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    normalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    supplier = relationship("SupplierModel", back_populates="attestations")
    assessment = relationship("AssessmentModel", back_populates="attestation", uselist=False, cascade="all, delete-orphan")
    follow_up_letters = relationship("FollowUpLetterModel", back_populates="attestation", cascade="all, delete-orphan")


class AssessmentModel(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    attestation_id: Mapped[str] = mapped_column(String(36), ForeignKey("attestation_cycles.id", ondelete="CASCADE"), unique=True, nullable=False)
    overall_risk_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0 to 100
    risk_tier: Mapped[str] = mapped_column(String(32), default="LOW")  # LOW, MEDIUM, HIGH, CRITICAL
    environmental_score: Mapped[float] = mapped_column(Float, default=0.0)
    social_score: Mapped[float] = mapped_column(Float, default=0.0)
    governance_score: Mapped[float] = mapped_column(Float, default=0.0)
    summary_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superdocs_diff_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    attestation = relationship("AttestationCycleModel", back_populates="assessment")
    findings = relationship("FindingModel", back_populates="assessment", cascade="all, delete-orphan")


class FindingModel(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    assessment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    pillar: Mapped[str] = mapped_column(String(32), nullable=False)  # ENVIRONMENTAL, SOCIAL, GOVERNANCE
    severity: Mapped[str] = mapped_column(String(32), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW, OBSERVATION
    standard_clause: Mapped[str] = mapped_column(String(255), nullable=False)
    shortfall_summary: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_exact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    review_decision: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING, ACCEPTED, REJECTED
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    assessment = relationship("AssessmentModel", back_populates="findings")


class FollowUpLetterModel(Base):
    __tablename__ = "follow_up_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    attestation_id: Mapped[str] = mapped_column(String(36), ForeignKey("attestation_cycles.id", ondelete="CASCADE"), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    superdocs_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    superdocs_export_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")  # DRAFT, APPROVED, SENT
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    attestation = relationship("AttestationCycleModel", back_populates="follow_up_letters")
