"""Input and output shapes.

Every produced sentence carries the span of the technician note it came from.
That is what makes "no fact was invented" checkable rather than asserted: a
sentence with no span did not come from the source, and the tests refuse it.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Element(str, Enum):
    COMPLAINT = "complaint"
    CAUSE = "cause"
    CORRECTION = "correction"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Vehicle(BaseModel):
    """Every field optional. A vehicle detail absent from the order is never
    filled in — not from the VIN, not from the DTC, not from anywhere."""

    year: int | None = None
    make: str | None = None
    model: str | None = None
    vin: str | None = None
    mileage: int | None = None


class RepairOrder(BaseModel):
    repair_order_id: str
    technician_note: str
    dtc_codes: list[str] = Field(default_factory=list)
    vehicle: Vehicle | None = None


class Evidence(BaseModel):
    """A verbatim span of the technician note.

    `start` and `end` index the original note, so a reviewer can highlight
    exactly what a sentence was built from.
    """

    text: str
    start: int
    end: int


class ElementResult(BaseModel):
    element: Element
    supported: bool
    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str | None = None


class Warning(BaseModel):
    code: str
    message: str
    evidence: list[Evidence] = Field(default_factory=list)


class NormalizedOrder(BaseModel):
    repair_order_id: str
    complaint: ElementResult
    cause: ElementResult
    correction: ElementResult

    dtc_codes: list[str] = Field(default_factory=list)
    measurements: list[str] = Field(default_factory=list)

    # Sentences that describe the job but belong to no required element —
    # odometer readings, customer contact, shop notes. Reported rather than
    # dropped: the brief asks for every technical fact kept, not only for none
    # invented, and forcing them into an element would be the invention.
    unplaced: list[Evidence] = Field(default_factory=list)

    missing_elements: list[Element] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)

    confidence: Confidence
    confidence_reasons: list[str] = Field(default_factory=list)

    @property
    def narrative(self) -> str:
        """The manufacturer-facing text."""
        return "\n\n".join(
            f"{element.element.value.upper()}:\n{element.text}"
            for element in (self.complaint, self.cause, self.correction)
        )

    @property
    def needs_review(self) -> bool:
        return bool(self.missing_elements) or self.confidence is not Confidence.HIGH


class BatchSummary(BaseModel):
    total: int
    high: int
    medium: int
    low: int
    with_missing_elements: int
    needs_review: int
    warnings: dict[str, int] = Field(default_factory=dict)
