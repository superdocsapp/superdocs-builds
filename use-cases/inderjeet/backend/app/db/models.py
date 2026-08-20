import uuid
from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.session import Base

class DisruptionBatch(Base):
    __tablename__ = "disruption_batches"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, nullable=False, default="INGESTED") # INGESTED, IMPACT_ANALYZED, DRAFTED, PENDING_APPROVAL, COMMITTED, FAILED
    disruption_details = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    total_operations_spent = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)

    travelers = relationship("TravelerManifest", back_populates="batch", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="batch", cascade="all, delete-orphan")

class TravelerManifest(Base):
    __tablename__ = "traveler_manifests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id = Column(String, ForeignKey("disruption_batches.id"), nullable=False)
    passenger_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    language = Column(String, nullable=False, default="en")
    loyalty_status = Column(String, nullable=False, default="STANDARD")
    original_itinerary_url = Column(String, nullable=True)
    updated_itinerary_url = Column(String, nullable=True)
    explanation_letter = Column(Text, nullable=True)
    voucher_status = Column(String, nullable=False, default="INELIGIBLE") # ELIGIBLE, INELIGIBLE, ISSUED
    approval_status = Column(String, nullable=False, default="PENDING") # PENDING, APPROVED, REJECTED
    cost_usd = Column(Float, default=0.0)
    operations_spent = Column(Integer, default=0)

    batch = relationship("DisruptionBatch", back_populates="travelers")
    vouchers = relationship("VoucherRecord", back_populates="traveler", cascade="all, delete-orphan")

class VoucherRecord(Base):
    __tablename__ = "voucher_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    traveler_id = Column(String, ForeignKey("traveler_manifests.id"), nullable=False)
    type = Column(String, nullable=False) # MEAL, HOTEL, TRANSPORT
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="USD")
    code = Column(String, nullable=False, default=lambda: str(uuid.uuid4())[:8].upper())
    issued_at = Column(DateTime(timezone=True), server_default=func.now())

    traveler = relationship("TravelerManifest", back_populates="vouchers")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, ForeignKey("disruption_batches.id"), nullable=False)
    stage = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("DisruptionBatch", back_populates="audit_logs")
