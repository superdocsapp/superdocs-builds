"""The typed record set.

Three messy record sets go in; typed records come out, and every derived statement
downstream carries the log entry ids it came from. The `sources` field is not
decoration — the traceability pass in `trace.py` resolves it, and a statement whose
sources do not resolve is reported rather than shipped.

The distinction the regulator cares about lives here too, in `Kind`:
OBSERVED statements are traceable to a log entry, ASSESSED statements are the team's
judgement. Nothing in the pipeline is allowed to be neither.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

ENTRY_ID = re.compile(r"^EL-\d{4}$")


class Kind(StrEnum):
    """What sort of statement this is, as it will appear in the report."""

    OBSERVED = "observed"  # traceable to at least one log entry
    ASSESSED = "assessed"  # the team's judgement, marked as judgement


class Category(StrEnum):
    """Event-log categories. Sections select their evidence by these."""

    WEATHER = "weather"
    OUTAGE = "outage"
    DISPATCH = "dispatch"
    RESTORATION = "restoration"
    COMMUNICATION = "communication"
    SAFETY = "safety"
    ASSESSMENT = "assessment"


class Event(BaseModel):
    """One storm. The unit of a report, and of the carry-forward."""

    event_id: str
    name: str
    utility: str
    consumers_served: int = Field(gt=0)
    started_at: datetime
    ended_at: datetime
    previous_event_id: str | None = None

    @model_validator(mode="after")
    def _ends_after_start(self) -> Event:
        if self.ended_at <= self.started_at:
            raise ValueError(f"{self.event_id}: ended_at must be after started_at")
        return self


class LogEntry(BaseModel):
    """One line of the event log. The atom of traceability.

    Everything the report asserts as fact must point back to one of these by id.
    """

    entry_id: str
    at: datetime
    category: Category
    feeder: str | None = None
    consumers_out: int | None = Field(default=None, ge=0)
    note: str

    # Declares an interruption to consumer counting. `counts_lost` opens a window in
    # which no count exists; `counts_resumed` closes it. Read from the records rather
    # than inferred from the spacing of readings: a long quiet stretch overnight is a
    # reporting cadence, not missing data, and guessing from spacing cannot tell the
    # two apart. The utility already knows which one it was, and logged it.
    flag: str | None = None

    @field_validator("entry_id")
    @classmethod
    def _well_formed_id(cls, v: str) -> str:
        if not ENTRY_ID.match(v):
            raise ValueError(f"malformed log entry id {v!r}, expected EL-0000")
        return v


class CrewRecord(BaseModel):
    """A crew mobilisation. `released_at` is deliberately optional: the real records
    have crews whose release was never logged, and the report must say so rather than
    invent a time."""

    crew_id: str
    crew_type: str
    home_base: str
    headcount: int = Field(gt=0)
    mobilized_at: datetime | None = None
    released_at: datetime | None = None
    mutual_aid: bool = False
    sources: list[str] = Field(default_factory=list)

    @property
    def hours_worked(self) -> float | None:
        """None when the records do not support the arithmetic."""
        if self.mobilized_at is None or self.released_at is None:
            return None
        return (self.released_at - self.mobilized_at).total_seconds() / 3600


class CustomerComm(BaseModel):
    """One outbound message to consumers."""

    comm_id: str
    sent_at: datetime
    channel: str
    audience: int = Field(ge=0)
    subject: str
    sources: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    """A single statement destined for the report.

    `text` is written by this tool from computed values, never by a model — the model
    is asked to write prose around figures it is given, so no number in the report can
    be a hallucination. OBSERVED claims must carry sources; ASSESSED claims must not
    pretend to.
    """

    claim_id: str
    kind: Kind
    section: str
    text: str
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sources_match_kind(self) -> Claim:
        if self.kind is Kind.OBSERVED and not self.sources:
            raise ValueError(f"{self.claim_id}: an observed claim needs at least one log entry")
        if self.kind is Kind.ASSESSED and self.sources:
            raise ValueError(
                f"{self.claim_id}: an assessed claim is judgement and must not cite log entries "
                "as if the records proved it"
            )
        return self

    def rendered(self) -> str:
        """The claim as it goes into the document, carrying its own citation."""
        if self.kind is Kind.OBSERVED:
            return f"{self.text} [{', '.join(self.sources)}]"
        return f"{self.text} [assessed]"


class LessonStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Lesson(BaseModel):
    """A lessons-learned item. This is the object that carries forward.

    It is opened in one event and lives until some later event closes it, which is why
    `opened_in_event` and `closed_in_event` are separate fields: the next report has to
    be able to say 'raised after Perseus, still open' without guessing.
    """

    lesson_id: str
    title: str
    detail: str
    owner: str
    opened_in_event: str
    status: LessonStatus = LessonStatus.OPEN
    closed_in_event: str | None = None
    closed_note: str | None = None
    closed_sources: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    # Why an item is still open after a later event looked at it. An item that carries
    # forward unexamined and an item that was examined and found unfixed are different
    # facts, and a regulator reading two consecutive reports can tell them apart here.
    carry_note: str | None = None
    carry_sources: list[str] = Field(default_factory=list)
    last_reviewed_event: str | None = None

    @model_validator(mode="after")
    def _closed_items_say_where(self) -> Lesson:
        if self.status is LessonStatus.CLOSED and not self.closed_in_event:
            raise ValueError(f"{self.lesson_id}: a closed lesson must name the event that closed it")
        if self.status is LessonStatus.OPEN and self.closed_in_event:
            raise ValueError(f"{self.lesson_id}: an open lesson cannot name a closing event")
        return self


class Corpus(BaseModel):
    """One event's three record sets, parsed and cross-checked."""

    event: Event
    log: list[LogEntry]
    crews: list[CrewRecord]
    comms: list[CustomerComm]

    def entry(self, entry_id: str) -> LogEntry | None:
        return next((e for e in self.log if e.entry_id == entry_id), None)

    def by_category(self, *categories: Category) -> list[LogEntry]:
        wanted = set(categories)
        return [e for e in self.log if e.category in wanted]

    @property
    def entry_ids(self) -> set[str]:
        return {e.entry_id for e in self.log}
