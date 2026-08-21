"""The typed record set.

Six record sets go in; typed records come out, and every derived statement downstream
carries the record ids it came from. The `sources` field is not decoration — the
traceability pass in `trace.py` resolves it, and a statement whose sources do not
resolve is reported rather than shipped.

Two distinctions the regulator cares about live here.

`Kind` separates OBSERVED statements (traceable to a record) from ASSESSED ones (the
team's judgement). Nothing in the pipeline is allowed to be neither.

`Source` separates *where a record came from*, and it is the reason the records are
six files rather than one. "A customer says a pole looks broken", "a transformer
reported itself out of service" and "a crew inspected and confirmed it" are three
different grades of evidence for the same fact. A single event log flattens them into
identical-looking lines. The id prefix carries the grade into the report itself, so a
reader seeing [TEL-0032] knows it is machine data and [COM-0014] knows it is a phone
call, without having to ask.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

ENTRY_ID = re.compile(r"^(WEA|TEL|DMG|CRW|COM|FLD)-\d{4}$")


class Kind(StrEnum):
    """What sort of statement this is, as it will appear in the report."""

    OBSERVED = "observed"  # traceable to at least one record
    ASSESSED = "assessed"  # the team's judgement, marked as judgement


class Source(StrEnum):
    """Which record set an entry came from — its grade of evidence.

    The value is the id prefix, so `Source.TELEMETRY` and `TEL-0032` are the same
    statement about provenance and cannot drift apart.
    """

    WEATHER = "WEA"  # an external feed: the met office, a monitoring mast
    TELEMETRY = "TEL"  # the plant reporting on itself: trips, faults, counts
    DAMAGE = "DMG"  # an asset recorded as damaged, with its own provenance
    CREW = "CRW"  # gang mobilisation and release
    COMMS = "COM"  # messages in both directions
    FIELD = "FLD"  # a human on site: safety, access, conditions


class Category(StrEnum):
    """What an entry is *about*. Sections select their evidence by these."""

    WEATHER = "weather"
    OUTAGE = "outage"
    DAMAGE = "damage"
    DISPATCH = "dispatch"
    RESTORATION = "restoration"
    COMMUNICATION = "communication"
    SAFETY = "safety"
    ACCESS = "access"  # flooding, blocked roads — why restoration stalled
    ASSESSMENT = "assessment"


class Direction(StrEnum):
    """Which way a message went. Inbound is the stream a single event log loses."""

    IN = "in"  # consumer to utility: a complaint, a fault report
    OUT = "out"  # utility to consumer: a notification


class AssetType(StrEnum):
    POLE = "pole"
    CONDUCTOR_SPAN = "conductor_span"
    TRANSFORMER = "transformer"
    CROSS_ARM = "cross_arm"
    INSULATOR = "insulator"


class DamageStatus(StrEnum):
    """How far a damage record has travelled from claim to repair.

    REPORTED is not a fact about the asset, it is a fact about someone's statement.
    Counting reported and confirmed damage together is how a report ends up asserting
    more broken poles than were ever broken.
    """

    REPORTED = "reported"  # someone said so; nobody has looked yet
    CONFIRMED = "confirmed"  # a crew went and saw it
    REPAIRED = "repaired"  # fixed and released


class ReportedBy(StrEnum):
    """Who first raised a damage record."""

    CUSTOMER = "customer"
    TELEMETRY = "telemetry"
    CREW = "crew"


class Event(BaseModel):
    """One storm. The unit of a report, and of the carry-forward."""

    event_id: str
    name: str
    utility: str
    substation: str = ""
    consumers_served: int = Field(gt=0)
    started_at: datetime
    ended_at: datetime
    previous_event_id: str | None = None

    # How long a consumer complaint may stay open before the report counts it late.
    # A field rather than a constant because it is a policy, not a fact: a four-hour
    # squall and a four-day flood cannot answer to the same number, and the utility
    # already knows which it is running under.
    complaint_target_hours: int = Field(default=24, gt=0)

    @model_validator(mode="after")
    def _ends_after_start(self) -> Event:
        if self.ended_at <= self.started_at:
            raise ValueError(f"{self.event_id}: ended_at must be after started_at")
        return self

    @property
    def duration_hours(self) -> float:
        return (self.ended_at - self.started_at).total_seconds() / 3600


class LogEntry(BaseModel):
    """One entry in the merged timeline. The atom of traceability.

    Not read from a file of its own. Every typed record projects into one of these, and
    `Corpus.log` is the six sets merged and sorted. That keeps a single chronological
    spine — which the timeline section needs — without a seventh file duplicating the
    other six and drifting out of step with them.
    """

    entry_id: str
    at: datetime
    category: Category
    source: Source
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
            raise ValueError(
                f"malformed record id {v!r}, expected one of WEA-/TEL-/DMG-/CRW-/COM-/FLD-0000"
            )
        return v

    @model_validator(mode="after")
    def _id_matches_source(self) -> LogEntry:
        if not self.entry_id.startswith(f"{self.source.value}-"):
            raise ValueError(
                f"{self.entry_id}: id prefix contradicts source {self.source.value}; the "
                "prefix is what tells a reader the grade of evidence, so it cannot lie"
            )
        return self


class WeatherReading(BaseModel):
    """A warning or an observation from outside the utility."""

    entry_id: str
    at: datetime
    kind: str  # "warning" or "observation"
    note: str
    issued_by: str = ""


class TelemetryReading(BaseModel):
    """The network reporting on itself: a trip, a fault, a count, a restoration.

    `device` is kept because a regulator asking "how did you know?" is entitled to the
    answer "RTU at Neamatpur said so at 18:22", not "it is in the log".
    """

    entry_id: str
    at: datetime
    category: Category
    device: str = ""
    feeder: str | None = None
    consumers_out: int | None = Field(default=None, ge=0)
    note: str
    flag: str | None = None


class DamageRecord(BaseModel):
    """One damaged asset, with where the claim came from and how far it got.

    `count` and `asset_type` are structured so the report's damage figures are summed
    here and handed over already computed. Left as prose inside a note, those numbers
    would be the only ones in the report a model could quietly rewrite.
    """

    entry_id: str
    reported_at: datetime
    asset_type: AssetType
    count: int = Field(gt=0)
    status: DamageStatus
    reported_by: ReportedBy
    feeder: str | None = None
    location: str = ""
    note: str = ""

    # The record that raised it — a consumer's call, a telemetry fault. Resolved against
    # the corpus, so a damage record cannot claim a phone call that never happened.
    source_ref: str | None = None
    confirmed_at: datetime | None = None
    repaired_at: datetime | None = None

    @model_validator(mode="after")
    def _status_matches_times(self) -> DamageRecord:
        if self.status is DamageStatus.REPAIRED and self.repaired_at is None:
            raise ValueError(f"{self.entry_id}: marked repaired with no repaired_at")
        if self.status is DamageStatus.REPORTED and self.confirmed_at is not None:
            raise ValueError(
                f"{self.entry_id}: has a confirmed_at but is still status 'reported' — "
                "confirmed damage and claimed damage must not be counted together"
            )
        return self


class CrewRecord(BaseModel):
    """A crew mobilisation. `released_at` is deliberately optional: the real records
    have crews whose release was never logged, and the report must say so rather than
    invent a time."""

    entry_id: str
    crew_type: str
    home_base: str
    headcount: int = Field(gt=0)
    assigned_to: str | None = None
    mobilized_at: datetime | None = None
    released_at: datetime | None = None
    mutual_aid: bool = False
    note: str = ""
    sources: list[str] = Field(default_factory=list)

    @property
    def hours_worked(self) -> float | None:
        """None when the records do not support the arithmetic."""
        if self.mobilized_at is None or self.released_at is None:
            return None
        return (self.released_at - self.mobilized_at).total_seconds() / 3600


class CommsRecord(BaseModel):
    """One message, in either direction.

    Outbound rows carry `audience` — how many consumers were reached. Inbound rows carry
    `audience` as the number of contacts received on that channel in that batch, and may
    carry `resolved_at`. An inbound message that is never resolved is the thing the
    complaints chart exists to show.
    """

    entry_id: str
    at: datetime
    direction: Direction
    channel: str  # SMS, IVR, WhatsApp, email, call centre, web
    audience: int = Field(ge=0)
    subject: str
    note: str = ""
    resolved_at: datetime | None = None
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _only_inbound_resolves(self) -> CommsRecord:
        if self.direction is Direction.OUT and self.resolved_at is not None:
            raise ValueError(
                f"{self.entry_id}: an outbound notification has nothing to resolve; "
                "resolved_at belongs to consumer contacts"
            )
        return self

    @property
    def open_hours(self) -> float | None:
        """How long this contact stayed open. None when it is outbound or still open."""
        if self.direction is Direction.OUT or self.resolved_at is None:
            return None
        return (self.resolved_at - self.at).total_seconds() / 3600


class FieldReport(BaseModel):
    """A human on site: a safety incident, blocked access, standing water.

    Distinct from telemetry because it is somebody's eyes rather than a device, and
    distinct from damage because not everything a crew reports is a broken asset. Water
    across a road stops restoration without breaking anything.
    """

    entry_id: str
    at: datetime
    category: Category
    location: str = ""
    feeder: str | None = None
    note: str
    reported_by: str = ""


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
            raise ValueError(f"{self.claim_id}: an observed claim needs at least one record")
        if self.kind is Kind.ASSESSED and self.sources:
            raise ValueError(
                f"{self.claim_id}: an assessed claim is judgement and must not cite records "
                "as if they proved it"
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
    """One event's six record sets, parsed, merged and cross-checked."""

    event: Event
    log: list[LogEntry]  # the merged spine, sorted by time
    weather: list[WeatherReading] = Field(default_factory=list)
    telemetry: list[TelemetryReading] = Field(default_factory=list)
    damage: list[DamageRecord] = Field(default_factory=list)
    crews: list[CrewRecord] = Field(default_factory=list)
    comms: list[CommsRecord] = Field(default_factory=list)
    field_reports: list[FieldReport] = Field(default_factory=list)

    def entry(self, entry_id: str) -> LogEntry | None:
        return next((e for e in self.log if e.entry_id == entry_id), None)

    def by_category(self, *categories: Category) -> list[LogEntry]:
        wanted = set(categories)
        return [e for e in self.log if e.category in wanted]

    def by_source(self, *sources: Source) -> list[LogEntry]:
        wanted = set(sources)
        return [e for e in self.log if e.source in wanted]

    @property
    def entry_ids(self) -> set[str]:
        """Every record id in the event, across all six sets.

        Deliberately wider than `log`. The merged timeline only carries records that
        have a place in time, so a crew whose mobilisation was never logged does not
        appear on it — but that crew record exists, and a lessons-learned item about
        exactly that missing time has to be able to cite it. A citation resolves to a
        record, not to a position on a timeline.
        """
        return (
            {e.entry_id for e in self.log}
            | {w.entry_id for w in self.weather}
            | {t.entry_id for t in self.telemetry}
            | {d.entry_id for d in self.damage}
            | {c.entry_id for c in self.crews}
            | {m.entry_id for m in self.comms}
            | {f.entry_id for f in self.field_reports}
        )

    @property
    def inbound(self) -> list[CommsRecord]:
        return [c for c in self.comms if c.direction is Direction.IN]

    @property
    def outbound(self) -> list[CommsRecord]:
        return [c for c in self.comms if c.direction is Direction.OUT]

    def damage_totals(self, *statuses: DamageStatus) -> dict[AssetType, int]:
        """Assets damaged, summed here so no model ever writes one of these numbers.

        Filtered by status on purpose: reported damage and confirmed damage are
        different claims and adding them together overstates the event.
        """
        wanted = set(statuses) or set(DamageStatus)
        totals: dict[AssetType, int] = {}
        for d in self.damage:
            if d.status in wanted:
                totals[d.asset_type] = totals.get(d.asset_type, 0) + d.count
        return totals
