"""
Persistent case store. Replaces the sample data/sample_cases.json fixture
with a real database so the checklist is always computed against the
current, live case record rather than a bundled snapshot.

Uses SQLAlchemy so this works against SQLite locally and Postgres in
production (Render's managed Postgres) with the same code path.
"""
from __future__ import annotations

import os
from datetime import datetime, date, timezone
from typing import Optional

from sqlalchemy import (
    create_engine, String, Boolean, Date, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./case_status_desk.db")

# Render/Heroku-style URLs sometimes come as postgres:// -- SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


class CaseRecord(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(255))
    client_language: Mapped[str] = mapped_column(String(16), default="en")
    case_type: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    documents: Mapped[list["DocumentRequirement"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    letters: Mapped[list["GeneratedLetter"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class DocumentRequirement(Base):
    """One required document for a case, and whether it's been received."""
    __tablename__ = "document_requirements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"))
    name: Mapped[str] = mapped_column(String(255))
    form_type: Mapped[str] = mapped_column(String(255))  # e.g. "certified copy with translation"
    received: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    case: Mapped["CaseRecord"] = relationship(back_populates="documents")


class GeneratedLetter(Base):
    """Audit trail: every letter ever drafted/exported for a case, who
    triggered it, and whether it was approved before sending."""
    __tablename__ = "generated_letters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"))
    session_id: Mapped[str] = mapped_column(String(128))
    stage_snapshot: Mapped[str] = mapped_column(String(64))
    outstanding_snapshot: Mapped[str] = mapped_column(Text)  # JSON string of checklist at generation time
    status: Mapped[str] = mapped_column(String(32), default="drafted")  # drafted|awaiting_approval|approved|exported|rejected
    requested_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    export_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    superdocs_document_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    superdocs_document_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    validation_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    validation_issues: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list of issues
    validation_overridden_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    case: Mapped["CaseRecord"] = relationship(back_populates="letters")


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()


def seed_from_json(json_path: str) -> None:
    """One-time migration helper: load the old sample_cases.json format
    into the database. Safe to re-run (upserts by case_id)."""
    import json as _json

    with open(json_path) as f:
        raw = _json.load(f)

    with get_session() as db:
        for entry in raw:
            case = db.get(CaseRecord, entry["case_id"])
            if case is None:
                case = CaseRecord(case_id=entry["case_id"])
                db.add(case)
            case.client_name = entry["client_name"]
            case.client_language = entry.get("language", "en")
            case.case_type = entry.get("case_type", "")
            case.stage = entry["stage"]

            case.documents.clear()
            for doc in entry.get("required_documents", []):
                case.documents.append(
                    DocumentRequirement(
                        name=doc["name"],
                        form_type=doc["form_type"],
                        received=doc.get("received", False),
                        due_date=date.fromisoformat(doc["due_date"]) if doc.get("due_date") else None,
                    )
                )
        db.commit()
