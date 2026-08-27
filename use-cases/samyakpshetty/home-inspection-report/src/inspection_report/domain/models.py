"""The inspection domain, typed.

The shape here is the card's shape: an inspection is walked **system by system**, each system
carries findings, and each finding carries a severity, the inspector's note, and photo
evidence. Report structure is derived from this model deterministically, which is what makes
"grouped correctly by system" a property the code guarantees rather than a thing the AI is
asked to remember.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class ReportStage(StrEnum):
    """Where an inspection is in its life. Drives what the UI offers next."""

    DRAFT = "draft"  # the inspector is still walking the property
    PREPARED = "prepared"  # rendered and uploaded; the AI pass may run
    IN_REVIEW = "in_review"  # proposals are at the human gate
    APPROVED = "approved"  # every proposal decided
    EXPORTED = "exported"  # a file exists


class Severity(BaseModel):
    """One level of the severity scale, loaded from ``config/severity.yaml``."""

    model_config = {"frozen": True}

    key: str
    rank: int
    label: str
    description: str
    colour: str


class InspectionSystem(BaseModel):
    """One inspection system, loaded from ``config/systems.yaml``."""

    model_config = {"frozen": True}

    key: str
    name: str
    blurb: str


class Photo(BaseModel):
    """A photograph attached to a finding.

    ``sha256`` is the identity: the same bytes are the same photo, so a re-run never pays to
    upload them twice. ``remote_url`` is the stable URL SuperDocs returns — treated as a
    capability secret, because that URL is readable by anyone who holds it and never expires.
    """

    id: UUID = Field(default_factory=uuid4)
    sha256: str
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    caption: str = ""
    remote_url: str = ""

    @property
    def uploaded(self) -> bool:
        return bool(self.remote_url)


class Finding(BaseModel):
    """One thing the inspector observed, in one system."""

    id: UUID = Field(default_factory=uuid4)
    system_key: str
    severity_key: str
    location: str = ""
    # What the inspector actually typed, in the field, in shorthand. Never overwritten.
    observation: str
    recommendation: str = ""
    # The buyer-readable rewrite, once a human has approved it. Empty until then, and the
    # export falls back to `observation` — so a failed or rejected rewrite costs the buyer
    # nothing but polish.
    plain_language: str = ""
    photos: list[Photo] = Field(default_factory=list)

    @field_validator("observation")
    @classmethod
    def _observation_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a finding needs an observation; that is the inspector's record")
        return v

    def prose(self) -> str:
        """The text that goes into the report: the approved rewrite, or the inspector's own."""
        return self.plain_language.strip() or self.observation.strip()


class Property(BaseModel):
    """The property under inspection. Invented data — see the README."""

    address_line: str
    city: str
    postcode: str = ""
    year_built: int | None = None
    property_type: str = ""

    def one_line(self) -> str:
        bits = [self.address_line, self.city, self.postcode]
        return ", ".join(b for b in bits if b)


class Inspector(BaseModel):
    """Who performed the inspection."""

    name: str
    licence_number: str = ""
    firm_name: str = ""


class Inspection(BaseModel):
    """One property, one visit, one report."""

    id: UUID = Field(default_factory=uuid4)
    property: Property
    inspector: Inspector
    inspected_on: dt.date
    template_key: str = "buyer_summary"
    stage: ReportStage = ReportStage.DRAFT
    findings: list[Finding] = Field(default_factory=list)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def findings_for(self, system_key: str) -> list[Finding]:
        return [f for f in self.findings if f.system_key == system_key]

    # Deliberately a method, not a @property: the field below is *called* `property`, which
    # shadows the builtin inside this class body. Keeping the domain name is worth more than
    # the attribute-access sugar.
    def photo_count(self) -> int:
        return sum(len(f.photos) for f in self.findings)
