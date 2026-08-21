"""Turn a corpus into claims.

Every number in the finished report is computed here, in Python, from the records —
never written by a model. The model is later asked to write prose *around* figures it
is handed, which is what makes a hallucinated restoration percentage structurally
impossible rather than merely unlikely.

Two rules hold throughout:

* An OBSERVED claim carries the records that support it. If the records cannot support
  a claim, no claim is produced and a Gap is recorded instead.
* An ASSESSED claim is the team's judgement and is marked as such. It never cites a
  record, because citing one would dress judgement up as evidence.

The timeline section is the one exception to "claims carry their own text", and
deliberately so. Its bullets are written by the model from a window's raw records —
see `windows.py` for why — so what this module computes for the timeline is *which
records fall in which window*, not the sentences. The citations still come from here,
and traceability still checks every one of them against the document that comes back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import (
    AssetType,
    Category,
    Claim,
    Corpus,
    DamageStatus,
    Direction,
    Kind,
    LogEntry,
    ReportedBy,
)
from .windows import Window, build_windows, coverage, window_hours

# Section keys. Order is report order.
OVERVIEW = "event_overview"
TIMELINE = "timeline"
DAMAGE = "damage_assessment"
MOBILISATION = "crew_mobilisation"
RESTORATION = "restoration_performance"
COMMUNICATIONS = "consumer_communications"

SECTION_TITLES = {
    OVERVIEW: "Event Overview",
    TIMELINE: "Timeline of Events",
    DAMAGE: "Damage Assessment",
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

    `sources` names the records the gap is *about*. A gap almost always points at
    something — the crew whose release was never logged, the contact that was never
    answered — and naming it in the text is how a reader finds it. Those names are real
    citations and are declared here, so the traceability pass resolves them instead of
    reporting the section for citing a record it was never given.
    """

    section: str
    subject: str
    detail: str
    sources: tuple[str, ...] = ()


@dataclass
class Reading:
    """One consumer-count observation, and where it came from."""

    at: datetime
    consumers_out: int
    entry_id: str


@dataclass
class ComplaintPoint:
    """One moment on the complaints chart: contacts in, contacts closed, still open."""

    at: datetime
    received: int  # cumulative contacts received
    resolved: int  # cumulative contacts resolved
    open_late: int  # of those still open, how many are past the target


@dataclass
class FactSet:
    """Everything derived from one event's records."""

    corpus: Corpus
    claims: list[Claim] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)
    windows: list[Window] = field(default_factory=list)
    complaints: list[ComplaintPoint] = field(default_factory=list)

    def for_section(self, section: str) -> list[Claim]:
        return [c for c in self.claims if c.section == section]

    def gaps_for(self, section: str) -> list[Gap]:
        return [g for g in self.gaps if g.section == section]

    def sources_for(self, section: str) -> list[str]:
        """The records a section is allowed to cite — nothing else goes in its instruction.

        The timeline draws its sources from the windows rather than from claims, because
        its prose has not been written yet. Everything else draws from its claims.
        """
        seen: set[str] = set()
        if section == TIMELINE:
            seen |= {s for w in self.windows for s in w.sources}
        for claim in self.for_section(section):
            seen |= set(claim.sources)
        # A gap names the record it is about, and that name is a citation like any other.
        for gap in self.gaps_for(section):
            seen |= set(gap.sources)
        return sorted(seen)


def declared_count_gaps(corpus: Corpus) -> list[tuple[LogEntry, LogEntry]]:
    """Windows in which the records say no consumer count exists.

    Paired from the log's own `counts_lost` / `counts_resumed` flags. An unclosed
    `counts_lost` runs to the last record, because a gap the utility never declared
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


def _asset(kind: AssetType, count: int) -> str:
    """'3 poles', '1 conductor span' — written from the structured fields, never parsed
    back out of a note."""
    word = kind.value.replace("_", " ")
    return f"{count:,} {word if count == 1 else word + 's'}"


def build_facts(corpus: Corpus) -> FactSet:
    """Derive every claim, every gap and every window for one event."""
    facts = FactSet(corpus=corpus)
    facts.readings = [
        Reading(at=e.at, consumers_out=e.consumers_out, entry_id=e.entry_id)
        for e in corpus.log
        if e.consumers_out is not None
    ]
    facts.windows = build_windows(corpus)
    facts.complaints = _complaint_curve(corpus)

    _overview(facts)
    _timeline(facts)
    _damage(facts)
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
            f"{ev.name} began affecting the {ev.substation or ev.utility} network at "
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
            f"of the {ev.consumers_served:,} consumers served by the substation, at "
            f"{peak.at:%H:%M on %d %B}",
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
    """The timeline is windows, not claims.

    What is computed here is the shape of the section — how many bullets, standing for
    how many records, at what window size — so that the compression is stated in the
    report rather than left for a reader to discover by counting.
    """
    c = facts.corpus
    if facts.windows:
        records, bullets = coverage(c, facts.windows)
        size = window_hours(c.event.duration_hours)
        facts.claims.append(
            Claim(
                claim_id="OBS-timeline-00",
                kind=Kind.OBSERVED,
                section=TIMELINE,
                text=(
                    f"The timeline below summarises {_plural(records, 'record')} into "
                    f"{_plural(bullets, 'entry', 'entries')}, one for each {size}-hour window "
                    f"in which anything was recorded. The window is {size} "
                    f"{'hour' if size == 1 else 'hours'} because the event ran "
                    f"{_duration(c.event.duration_hours)}"
                ),
                sources=[facts.windows[0].sources[0]],
            )
        )

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
                sources=(start.entry_id, end.entry_id),
            )
        )


def _damage(facts: FactSet) -> None:
    """Damage, summed from structured fields.

    Confirmed and reported damage are counted separately and never added together. A
    consumer saying a pole looks broken and a crew confirming it are different claims,
    and a report that totals them asserts more broken assets than were ever broken.
    """
    c = facts.corpus
    if not c.damage:
        return
    n = 0

    confirmed = c.damage_totals(DamageStatus.CONFIRMED, DamageStatus.REPAIRED)
    if confirmed:
        n += 1
        listed = ", ".join(_asset(k, v) for k, v in sorted(confirmed.items(), key=lambda kv: -kv[1]))
        sources = sorted(
            d.entry_id
            for d in c.damage
            if d.status in (DamageStatus.CONFIRMED, DamageStatus.REPAIRED)
        )
        _claim(
            facts,
            DAMAGE,
            n,
            Kind.OBSERVED,
            f"Confirmed damage across the substation area: {listed}",
            sources,
        )

    # Where the damage records came from. This is the distinction the six-file split
    # exists to preserve, so the report states it rather than letting it disappear.
    by_source: dict[ReportedBy, int] = {}
    for d in c.damage:
        by_source[d.reported_by] = by_source.get(d.reported_by, 0) + 1
    if len(by_source) > 1:
        n += 1
        names = {
            ReportedBy.CUSTOMER: "a consumer contact",
            ReportedBy.TELEMETRY: "network telemetry",
            ReportedBy.CREW: "a crew on site",
        }
        listed = ", ".join(
            f"{count} by {names[src]}" for src, count in sorted(by_source.items(), key=lambda kv: -kv[1])
        )
        _claim(
            facts,
            DAMAGE,
            n,
            Kind.OBSERVED,
            f"{_plural(len(c.damage), 'damage record')} were raised: {listed}",
            sorted(d.entry_id for d in c.damage),
        )

    repaired = [d for d in c.damage if d.status is DamageStatus.REPAIRED]
    if repaired:
        n += 1
        spans = [
            _hours(d.confirmed_at or d.reported_at, d.repaired_at)
            for d in repaired
            if d.repaired_at
        ]
        longest = max(repaired, key=lambda d: _hours(d.confirmed_at or d.reported_at, d.repaired_at))
        _claim(
            facts,
            DAMAGE,
            n,
            Kind.OBSERVED,
            f"{_plural(len(repaired), 'damage record')} were repaired and released, taking "
            f"{_duration(sum(spans) / len(spans))} on average from confirmation to repair. The "
            f"longest was {longest.entry_id} at {longest.location or 'an unnamed location'}, "
            f"{_duration(_hours(longest.confirmed_at or longest.reported_at, longest.repaired_at))}",
            sorted(d.entry_id for d in repaired),
        )

    # Damage nobody went and looked at. Reported by someone, never inspected, never
    # repaired — and therefore not in any total above.
    unverified = [d for d in c.damage if d.status is DamageStatus.REPORTED]
    for d in unverified:
        facts.gaps.append(
            Gap(
                section=DAMAGE,
                subject=d.entry_id,
                detail=(
                    f"{_asset(d.asset_type, d.count)} at {d.location or 'an unnamed location'} "
                    f"({d.entry_id}) was reported by {d.reported_by.value} and never inspected, so "
                    "the records establish neither that it is damaged nor that it is sound. It is "
                    "excluded from the confirmed totals above."
                ),
                sources=(d.entry_id,),
            )
        )

    n += 1
    _claim(
        facts,
        DAMAGE,
        n,
        Kind.ASSESSED,
        "The damage profile is consistent with wind and tree contact rather than with any "
        "underlying asset condition, and no pattern of premature failure is apparent",
        [],
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
        dispatch_sources[:2] or [crews[0].entry_id],
    )

    aid = [cr for cr in crews if cr.mutual_aid]
    if aid:
        n += 1
        _claim(
            facts,
            MOBILISATION,
            n,
            Kind.OBSERVED,
            f"{_plural(len(aid), 'mutual-aid crew')} totalling "
            f"{sum(cr.headcount for cr in aid):,} personnel "
            f"{'was' if len(aid) == 1 else 'were'} requested from "
            f"{', '.join(sorted({cr.home_base for cr in aid}))}",
            sorted(cr.entry_id for cr in aid),
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
            sorted(cr.entry_id for cr in computable)[:3],
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
                subject=cr.entry_id,
                detail=(
                    f"Crew {cr.entry_id} ({cr.headcount} personnel from {cr.home_base}) has no "
                    f"{' and no '.join(missing)} in the records, so its hours cannot be computed "
                    "and are excluded from the personnel-hours total."
                ),
                sources=(cr.entry_id,),
            )
        )

    # Only judge the mutual-aid decision when there was one to judge. An event the
    # section handled with its own gangs has nothing to say here, and asserting that aid
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
    c = facts.corpus
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

    # Why restoration stalled, where the records say so. Standing water and blocked
    # access are the reason a multi-day restoration is multi-day, and a report that
    # omits them invites the reader to conclude the crews were slow.
    blocked = c.by_category(Category.ACCESS)
    if blocked:
        n += 1
        _claim(
            facts,
            RESTORATION,
            n,
            Kind.OBSERVED,
            f"{_plural(len(blocked), 'access constraint')} were recorded during restoration, "
            "each one holding work on a section until it cleared",
            [e.entry_id for e in blocked],
        )

    n += 1
    _claim(
        facts,
        RESTORATION,
        n,
        Kind.ASSESSED,
        "Restoration sequencing prioritised the highest-count feeders correctly, and the "
        "resulting curve is consistent with the damage sustained and the access available",
        [],
    )


def _complaint_curve(corpus: Corpus) -> list[ComplaintPoint]:
    """Consumer contacts received against contacts closed, over the event.

    The gap between the two lines is the backlog. The third series counts the part of
    that backlog that has been open longer than the event's own target, which is where
    a commission looks first.
    """
    inbound = sorted(corpus.inbound, key=lambda m: m.at)
    if not inbound:
        return []

    target = corpus.event.complaint_target_hours
    moments = sorted(
        {m.at for m in inbound}
        | {m.resolved_at for m in inbound if m.resolved_at}
        | {corpus.event.ended_at}
    )

    points: list[ComplaintPoint] = []
    for at in moments:
        received = sum(m.audience for m in inbound if m.at <= at)
        resolved = sum(m.audience for m in inbound if m.resolved_at and m.resolved_at <= at)
        late = sum(
            m.audience
            for m in inbound
            if m.at <= at
            and not (m.resolved_at and m.resolved_at <= at)
            and _hours(m.at, at) > target
        )
        points.append(ComplaintPoint(at=at, received=received, resolved=resolved, open_late=late))
    return points


def _communications(facts: FactSet) -> None:
    """Both directions. Outbound is what the utility said; inbound is what it was told.

    A single event log records only the first. The second is usually the larger stream
    and is the one a commission asks about — how many consumers called, and how long
    they waited.
    """
    c = facts.corpus
    if not c.comms:
        return
    ev = c.event
    inbound, outbound = c.inbound, c.outbound
    first_out = next((e for e in c.log if e.category is Category.OUTAGE), None)
    n = 0

    if first_out and outbound:
        first_msg = min(outbound, key=lambda m: m.at)
        n += 1
        lag = _hours(first_out.at, first_msg.at)
        _claim(
            facts,
            COMMUNICATIONS,
            n,
            Kind.OBSERVED,
            f"The first consumer notification was issued at {first_msg.at:%H:%M on %d %B}, "
            f"{_duration(lag)} after the first recorded outage",
            [first_out.entry_id, first_msg.entry_id],
        )

    if outbound:
        n += 1
        channels = sorted({m.channel for m in outbound})
        _claim(
            facts,
            COMMUNICATIONS,
            n,
            Kind.OBSERVED,
            f"{_plural(len(outbound), 'notification')} were issued to consumers across "
            f"{_plural(len(channels), 'channel')} ({', '.join(channels)}), reaching "
            f"{sum(m.audience for m in outbound):,} recipients in total",
            sorted(m.entry_id for m in outbound)[:3],
        )

    if inbound:
        n += 1
        channels = sorted({m.channel for m in inbound})
        _claim(
            facts,
            COMMUNICATIONS,
            n,
            Kind.OBSERVED,
            f"{sum(m.audience for m in inbound):,} consumer contacts were received across "
            f"{_plural(len(channels), 'channel')} ({', '.join(channels)}) in "
            f"{_plural(len(inbound), 'batch', 'batches')}",
            sorted(m.entry_id for m in inbound)[:3],
        )

        closed = [m for m in inbound if m.resolved_at]
        if closed:
            n += 1
            waits = [m.open_hours for m in closed if m.open_hours is not None]
            late = [m for m in closed if m.open_hours and m.open_hours > ev.complaint_target_hours]
            tail = (
                f", of which {_plural(sum(m.audience for m in late), 'contact')} closed later than "
                f"the {ev.complaint_target_hours}-hour target"
                if late
                else f", all inside the {ev.complaint_target_hours}-hour target"
            )
            _claim(
                facts,
                COMMUNICATIONS,
                n,
                Kind.OBSERVED,
                f"{sum(m.audience for m in closed):,} of those contacts were resolved, averaging "
                f"{_duration(sum(waits) / len(waits))} from contact to resolution{tail}",
                sorted(m.entry_id for m in closed)[:3],
            )

        # Contacts still open when the event closed. Each one is a consumer who called
        # and never heard back, which is a fact about the response, not a rounding error.
        still_open = [m for m in inbound if not m.resolved_at]
        for m in still_open:
            waited = _hours(m.at, ev.ended_at)
            facts.gaps.append(
                Gap(
                    section=COMMUNICATIONS,
                    subject=m.entry_id,
                    detail=(
                        f"{_plural(m.audience, 'consumer contact')} received by {m.channel} at "
                        f"{m.at:%H:%M on %d %B} (“{m.subject}”, {m.entry_id}) carried no resolution "
                        f"time when the event closed, {_duration(waited)} later. The records do not "
                        "show whether it was answered."
                    ),
                    sources=(m.entry_id,),
                )
            )

    unlogged = [m for m in c.comms if not m.sources]
    if unlogged:
        facts.gaps.append(
            Gap(
                section=COMMUNICATIONS,
                subject="corroboration",
                detail=(
                    f"{_plural(len(unlogged), 'message')} "
                    f"({', '.join(sorted(m.entry_id for m in unlogged))}) carry no reference to a "
                    "telemetry or field record, so they cannot be corroborated against the rest "
                    "of the event."
                ),
                sources=tuple(sorted(m.entry_id for m in unlogged)),
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
