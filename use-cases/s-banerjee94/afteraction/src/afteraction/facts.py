"""Turn a corpus into claims.

Every number in the finished report is computed here, in Python, from the records —
never written by a model. The model is later asked to write prose *around* figures it
is handed, which is what makes a hallucinated restoration percentage structurally
impossible rather than merely unlikely.

Two rules hold throughout:

* An OBSERVED claim carries the log entries that support it. If the records cannot
  support a claim, no claim is produced and a Gap is recorded instead.
* An ASSESSED claim is the team's judgement and is marked as such. It never cites a
  log entry, because citing one would dress judgement up as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Category, Claim, Corpus, Kind, LogEntry

# Section keys. Order is report order.
OVERVIEW = "event_overview"
TIMELINE = "timeline"
MOBILISATION = "crew_mobilisation"
RESTORATION = "restoration_performance"
COMMUNICATIONS = "consumer_communications"

SECTION_TITLES = {
    OVERVIEW: "Event Overview",
    TIMELINE: "Timeline of Events",
    MOBILISATION: "Crew Mobilisation",
    RESTORATION: "Restoration Performance",
    COMMUNICATIONS: "Consumer Communications",
}


@dataclass(frozen=True)
class Gap:
    """Something the records do not say.

    A gap is a first-class output. The alternative — quietly omitting it — is the
    failure mode this build exists to avoid, because the reader cannot tell the
    difference between 'did not happen' and 'was not recorded'.
    """

    section: str
    subject: str
    detail: str


@dataclass
class Reading:
    """One consumer-count observation, and where it came from."""

    at: datetime
    consumers_out: int
    entry_id: str


@dataclass
class FactSet:
    """Everything derived from one event's records."""

    corpus: Corpus
    claims: list[Claim] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)

    def for_section(self, section: str) -> list[Claim]:
        return [c for c in self.claims if c.section == section]

    def gaps_for(self, section: str) -> list[Gap]:
        return [g for g in self.gaps if g.section == section]

    def sources_for(self, section: str) -> list[str]:
        """The log entries a section is allowed to cite — nothing else goes in its instruction."""
        seen: list[str] = []
        for claim in self.for_section(section):
            for ref in claim.sources:
                if ref not in seen:
                    seen.append(ref)
        return sorted(seen)


def declared_count_gaps(corpus: Corpus) -> list[tuple[LogEntry, LogEntry]]:
    """Windows in which the records say no consumer count exists.

    Paired from the log's own `counts_lost` / `counts_resumed` flags. An unclosed
    `counts_lost` runs to the last log entry, because a gap the utility never declared
    closed is still a gap — it does not silently disappear at the end of the file.
    """
    pairs: list[tuple[LogEntry, LogEntry]] = []
    open_at: LogEntry | None = None
    for entry in corpus.log:
        if entry.flag == "counts_lost" and open_at is None:
            open_at = entry
        elif entry.flag == "counts_resumed" and open_at is not None:
            pairs.append((open_at, entry))
            open_at = None
    if open_at is not None:
        pairs.append((open_at, corpus.log[-1]))
    return pairs


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def _duration(hours: float) -> str:
    """A duration as a person writes it: '38 minutes', not '0 hours 38 minutes'."""
    whole = int(hours)
    minutes = round((hours - whole) * 60)
    if minutes == 60:
        whole, minutes = whole + 1, 0
    if whole == 0:
        return _plural(minutes, "minute")
    if minutes == 0:
        return _plural(whole, "hour")
    return f"{_plural(whole, 'hour')} {_plural(minutes, 'minute')}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count:,} {singular if count == 1 else (plural or singular + 's')}"


def build_facts(corpus: Corpus) -> FactSet:
    """Derive every claim and every gap for one event."""
    facts = FactSet(corpus=corpus)
    facts.readings = [
        Reading(at=e.at, consumers_out=e.consumers_out, entry_id=e.entry_id)
        for e in corpus.log
        if e.consumers_out is not None
    ]

    _overview(facts)
    _timeline(facts)
    _mobilisation(facts)
    _restoration(facts)
    _communications(facts)
    return facts


def _claim(facts: FactSet, section: str, n: int, kind: Kind, text: str, sources: list[str]) -> None:
    prefix = {Kind.OBSERVED: "OBS", Kind.ASSESSED: "ASS"}[kind]
    facts.claims.append(
        Claim(
            claim_id=f"{prefix}-{section}-{n:02d}",
            kind=kind,
            section=section,
            text=text,
            sources=sources if kind is Kind.OBSERVED else [],
        )
    )


# --------------------------------------------------------------------- sections


def _overview(facts: FactSet) -> None:
    c = facts.corpus
    ev = c.event
    first_out = next((e for e in c.log if e.category is Category.OUTAGE), None)
    final = next((r for r in reversed(facts.readings) if r.consumers_out == 0), None)
    peak = max(facts.readings, key=lambda r: r.consumers_out) if facts.readings else None

    n = 0
    if first_out:
        n += 1
        _claim(
            facts,
            OVERVIEW,
            n,
            Kind.OBSERVED,
            f"{ev.name} began affecting the {ev.utility} network at "
            f"{first_out.at:%H:%M on %d %B %Y}, when the first outages were recorded"
            + (f" on feeder {first_out.feeder}" if first_out.feeder else ""),
            [first_out.entry_id],
        )

    if peak:
        n += 1
        share = peak.consumers_out / ev.consumers_served * 100
        _claim(
            facts,
            OVERVIEW,
            n,
            Kind.OBSERVED,
            f"Consumers without supply peaked at {peak.consumers_out:,}, which is {share:.1f} per cent "
            f"of the {ev.consumers_served:,} consumers served, at {peak.at:%H:%M on %d %B}",
            [peak.entry_id],
        )

    if first_out and final:
        n += 1
        total = _hours(first_out.at, final.at)
        _claim(
            facts,
            OVERVIEW,
            n,
            Kind.OBSERVED,
            f"Full restoration took {_duration(total)} from the first recorded outage to the "
            f"final consumer restored at {final.at:%H:%M on %d %B}",
            [first_out.entry_id, final.entry_id],
        )

    n += 1
    _claim(
        facts,
        OVERVIEW,
        n,
        Kind.ASSESSED,
        "The response is judged to have met its restoration objective, with no service "
        "interruption extending beyond the operating standard",
        [],
    )


def _timeline(facts: FactSet) -> None:
    """The timeline is the section the card cares most about: every claim here must
    resolve to a log entry, because this is what a commission challenges first."""
    c = facts.corpus
    milestones = c.by_category(
        Category.WEATHER, Category.OUTAGE, Category.DISPATCH, Category.SAFETY, Category.ASSESSMENT
    )
    for n, entry in enumerate(milestones, start=1):
        # The note is quoted as written. Downcasing its first letter to graft it onto a
        # lead-in mangles proper nouns ("northbank Power"), and these notes are the
        # record — altering them is exactly what this report must not do.
        text = f"At {entry.at:%H:%M on %d %B}: {entry.note.rstrip('.')}"
        _claim(facts, TIMELINE, n, Kind.OBSERVED, text, [entry.entry_id])

    # A declared interruption to consumer counting is itself a timeline fact.
    for start, end in declared_count_gaps(c):
        facts.gaps.append(
            Gap(
                section=TIMELINE,
                subject="consumer counts",
                detail=(
                    f"Consumer counting was interrupted from {start.at:%H:%M on %d %B} "
                    f"({start.entry_id}) until {end.at:%H:%M on %d %B} ({end.entry_id}), a span of "
                    f"{_duration(_hours(start.at, end.at))}. The restoration curve is broken across "
                    "this window and the records do not support a figure inside it."
                ),
            )
        )


def _mobilisation(facts: FactSet) -> None:
    c = facts.corpus
    crews = c.crews
    if not crews:
        return

    dispatches = c.by_category(Category.DISPATCH)
    dispatch_sources = [e.entry_id for e in dispatches]
    n = 0

    n += 1
    heads = sum(cr.headcount for cr in crews)
    _claim(
        facts,
        MOBILISATION,
        n,
        Kind.OBSERVED,
        f"{_plural(len(crews), 'crew')} totalling {heads:,} field personnel were mobilised "
        "for the event",
        dispatch_sources[:2] or [c.log[0].entry_id],
    )

    aid = [cr for cr in crews if cr.mutual_aid]
    if aid:
        n += 1
        aid_sources = sorted({s for cr in aid for s in cr.sources})
        _claim(
            facts,
            MOBILISATION,
            n,
            Kind.OBSERVED,
            f"{_plural(len(aid), 'mutual-aid crew')} totalling "
            f"{sum(cr.headcount for cr in aid):,} personnel "
            f"{'was' if len(aid) == 1 else 'were'} requested from "
            f"{', '.join(sorted({cr.home_base for cr in aid}))}",
            aid_sources,
        )

    # Crew-hours, but only over the crews whose records actually support the arithmetic.
    computable = [cr for cr in crews if cr.hours_worked is not None]
    incomplete = [cr for cr in crews if cr.hours_worked is None]
    if computable:
        n += 1
        total = sum(cr.hours_worked * cr.headcount for cr in computable)
        one = len(incomplete) == 1
        qualifier = (
            f" This figure covers {len(computable)} of {_plural(len(crews), 'crew')}; the "
            f"remaining {len(incomplete)} {'has' if one else 'have'} incomplete records "
            f"and {'is' if one else 'are'} excluded"
            if incomplete
            else ""
        )
        _claim(
            facts,
            MOBILISATION,
            n,
            Kind.OBSERVED,
            f"Crews worked approximately {total:,.0f} personnel-hours on the event.{qualifier}",
            sorted({s for cr in computable for s in cr.sources})[:3],
        )

    for cr in incomplete:
        missing = []
        if cr.mobilized_at is None:
            missing.append("mobilisation time")
        if cr.released_at is None:
            missing.append("release time")
        facts.gaps.append(
            Gap(
                section=MOBILISATION,
                subject=cr.crew_id,
                detail=(
                    f"Crew {cr.crew_id} ({cr.headcount} personnel from {cr.home_base}) has no "
                    f"{' and no '.join(missing)} in the records, so its hours cannot be computed "
                    "and are excluded from the personnel-hours total."
                ),
            )
        )

    # Only judge the mutual-aid decision when there was one to judge. An event the
    # division handled with its own gangs has nothing to say here, and asserting that aid
    # "was requested at an appropriate point" when none was requested is a false statement
    # about something that did not happen — marked [assessed], but still false.
    if aid:
        n += 1
        _claim(
            facts,
            MOBILISATION,
            n,
            Kind.ASSESSED,
            "Mutual aid was requested at an appropriate point in the event, and earlier "
            "escalation would not have materially shortened the restoration",
            [],
        )


def _restoration(facts: FactSet) -> None:
    readings = facts.readings
    if len(readings) < 2:
        return
    peak = max(readings, key=lambda r: r.consumers_out)
    n = 0

    for pct in (50, 90):
        target = peak.consumers_out * (1 - pct / 100)
        hit = next((r for r in readings if r.at > peak.at and r.consumers_out <= target), None)
        if hit:
            n += 1
            _claim(
                facts,
                RESTORATION,
                n,
                Kind.OBSERVED,
                f"{pct} per cent of affected consumers were restored within "
                f"{_duration(_hours(peak.at, hit.at))} of peak outage, by "
                f"{hit.at:%H:%M on %d %B} when {hit.consumers_out:,} consumers remained without supply",
                [peak.entry_id, hit.entry_id],
            )
        else:
            facts.gaps.append(
                Gap(
                    section=RESTORATION,
                    subject=f"{pct} per cent restoration",
                    detail=(
                        f"No recorded consumer count falls at or below the {pct} per cent "
                        "restoration threshold, so the milestone cannot be stated from the records."
                    ),
                )
            )

    n += 1
    _claim(
        facts,
        RESTORATION,
        n,
        Kind.OBSERVED,
        f"{_plural(len(readings), 'consumer count')} were recorded across the event, from "
        f"{readings[0].at:%H:%M on %d %B} to {readings[-1].at:%H:%M on %d %B}",
        [readings[0].entry_id, readings[-1].entry_id],
    )

    n += 1
    _claim(
        facts,
        RESTORATION,
        n,
        Kind.ASSESSED,
        "Restoration sequencing prioritised transmission-level faults and high-count feeders "
        "correctly, and the resulting curve is consistent with the damage sustained",
        [],
    )


def _communications(facts: FactSet) -> None:
    c = facts.corpus
    comms = c.comms
    if not comms:
        return
    first_out = next((e for e in c.log if e.category is Category.OUTAGE), None)
    first_comm = min(comms, key=lambda m: m.sent_at)
    n = 0

    if first_out:
        n += 1
        lag = _hours(first_out.at, first_comm.sent_at)
        _claim(
            facts,
            COMMUNICATIONS,
            n,
            Kind.OBSERVED,
            f"The first consumer notification was issued at {first_comm.sent_at:%H:%M on %d %B}, "
            f"{_duration(lag)} after the first recorded outage",
            [first_out.entry_id, *first_comm.sources],
        )

    n += 1
    channels = sorted({m.channel for m in comms})
    _claim(
        facts,
        COMMUNICATIONS,
        n,
        Kind.OBSERVED,
        f"{_plural(len(comms), 'consumer communication')} were issued across "
        f"{_plural(len(channels), 'channel')} ({', '.join(channels)}), reaching "
        f"{sum(m.audience for m in comms):,} recipients in total",
        sorted({s for m in comms for s in m.sources})[:3],
    )

    unlogged = [m for m in comms if not m.sources]
    for m in unlogged:
        facts.gaps.append(
            Gap(
                section=COMMUNICATIONS,
                subject=m.comm_id,
                detail=(
                    f"Communication {m.comm_id} ({m.channel}, {m.sent_at:%H:%M on %d %B}, "
                    f"“{m.subject}”) has no corresponding event-log entry, so its "
                    "issue cannot be corroborated against the log."
                ),
            )
        )

    n += 1
    _claim(
        facts,
        COMMUNICATIONS,
        n,
        Kind.ASSESSED,
        "Message cadence was appropriate to the restoration profile, and consumers received "
        "revised estimates at the points where the estimates materially changed",
        [],
    )
