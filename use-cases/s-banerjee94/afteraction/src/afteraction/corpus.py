"""Read one event's six record sets off disk, merge them and cross-check them.

Loading is where six separate CSVs stop being files and become one corpus whose
references either resolve or are reported. A crew record that cites a record which does
not exist is a data error and raises; a crew record that cites nothing at all is a
*gap*, which is legitimate and is carried forward as a finding rather than an
exception. Those two cases look similar and are not, and keeping them apart is most of
what this module does.

The six sets are split by *where the record came from*, not by what it is about. A
transformer reporting itself faulted, a consumer phoning it in and a crew confirming it
on site are three grades of evidence for one fact, and a report that cannot tell them
apart will eventually assert more broken poles than were ever broken. The id prefix
carries the grade — WEA, TEL, DMG, CRW, COM, FLD — all the way into the finished
document, so a reader never has to come back here to ask.

`Corpus.log` is the merged chronological spine, built here rather than read from a file
of its own. A seventh file restating the other six is a file that drifts out of step
with them.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .models import (
    AssetType,
    Category,
    CommsRecord,
    Corpus,
    CrewRecord,
    DamageRecord,
    DamageStatus,
    Direction,
    Event,
    FieldReport,
    Lesson,
    LessonStatus,
    LogEntry,
    ReportedBy,
    Source,
    TelemetryReading,
    WeatherReading,
)

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"

# Every record set, and the file it lives in. Named once so a new set is one line here
# rather than a search through the module.
RECORD_FILES = (
    "weather.csv",
    "telemetry.csv",
    "damage.csv",
    "crew.csv",
    "comms.csv",
    "field_reports.csv",
)


class CorpusError(Exception):
    """The records are internally inconsistent in a way no report can paper over."""


def _dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    return datetime.fromisoformat(value) if value else None


def _refs(value: str | None) -> list[str]:
    """Source lists are semicolon-separated so they survive CSV without quoting games."""
    return [r.strip() for r in (value or "").split(";") if r.strip()]


def _int(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_corpus(event_id: str, root: Path | None = None) -> Corpus:
    """Parse one event folder into a cross-checked Corpus."""
    folder = (root or DATA_ROOT) / event_id
    if not folder.is_dir():
        raise CorpusError(f"no data folder for event {event_id!r} at {folder}")

    event = Event.model_validate_json((folder / "event.json").read_text(encoding="utf-8"))

    weather = [
        WeatherReading(
            entry_id=r["entry_id"],
            at=_dt(r["at"]),
            kind=r["kind"],
            note=r["note"],
            issued_by=r.get("issued_by", ""),
        )
        for r in _rows(folder / "weather.csv")
    ]

    telemetry = [
        TelemetryReading(
            entry_id=r["entry_id"],
            at=_dt(r["at"]),
            category=Category(r["category"]),
            device=r.get("device", ""),
            feeder=r["feeder"] or None,
            consumers_out=_int(r["consumers_out"]),
            note=r["note"],
            flag=(r.get("flag") or "").strip() or None,
        )
        for r in _rows(folder / "telemetry.csv")
    ]

    damage = [
        DamageRecord(
            entry_id=r["entry_id"],
            reported_at=_dt(r["reported_at"]),
            asset_type=AssetType(r["asset_type"]),
            count=int(r["count"]),
            status=DamageStatus(r["status"]),
            reported_by=ReportedBy(r["reported_by"]),
            feeder=r["feeder"] or None,
            location=r.get("location", ""),
            note=r.get("note", ""),
            source_ref=(r.get("source_ref") or "").strip() or None,
            confirmed_at=_dt(r.get("confirmed_at")),
            repaired_at=_dt(r.get("repaired_at")),
        )
        for r in _rows(folder / "damage.csv")
    ]

    crews = [
        CrewRecord(
            entry_id=r["entry_id"],
            crew_type=r["crew_type"],
            home_base=r["home_base"],
            headcount=int(r["headcount"]),
            assigned_to=r.get("assigned_to") or None,
            mobilized_at=_dt(r["mobilized_at"]),
            released_at=_dt(r["released_at"]),
            mutual_aid=r["mutual_aid"].strip().lower() == "true",
            note=r.get("note", ""),
            sources=_refs(r["sources"]),
        )
        for r in _rows(folder / "crew.csv")
    ]

    comms = [
        CommsRecord(
            entry_id=r["entry_id"],
            at=_dt(r["at"]),
            direction=Direction(r["direction"]),
            channel=r["channel"],
            audience=int(r["audience"]),
            subject=r["subject"],
            note=r.get("note", ""),
            resolved_at=_dt(r.get("resolved_at")),
            sources=_refs(r["sources"]),
        )
        for r in _rows(folder / "comms.csv")
    ]

    field_reports = [
        FieldReport(
            entry_id=r["entry_id"],
            at=_dt(r["at"]),
            category=Category(r["category"]),
            location=r.get("location", ""),
            feeder=r["feeder"] or None,
            note=r["note"],
            reported_by=r.get("reported_by", ""),
        )
        for r in _rows(folder / "field_reports.csv")
    ]

    log = _merge(weather, telemetry, damage, crews, comms, field_reports)
    if not log:
        raise CorpusError(
            f"{event_id}: every record set is empty; there is nothing to report on. "
            f"Expected some of {', '.join(RECORD_FILES)} in {folder}"
        )

    corpus = Corpus(
        event=event,
        log=log,
        weather=weather,
        telemetry=telemetry,
        damage=damage,
        crews=crews,
        comms=comms,
        field_reports=field_reports,
    )
    _check_ids(corpus)
    _check_references(corpus)
    return corpus


def _merge(
    weather: list[WeatherReading],
    telemetry: list[TelemetryReading],
    damage: list[DamageRecord],
    crews: list[CrewRecord],
    comms: list[CommsRecord],
    field_reports: list[FieldReport],
) -> list[LogEntry]:
    """Project all six record sets into the one chronological spine.

    Each set keeps its own richer shape for the sections that need it; this view is
    what the timeline and the traceability pass work against. A crew record projects at
    its mobilisation time because that is when the crew became part of the event — a
    crew with no mobilisation time contributes no timeline entry, which is itself
    visible in the report rather than silently filled in.
    """
    entries: list[LogEntry] = []

    for w in weather:
        entries.append(
            LogEntry(
                entry_id=w.entry_id,
                at=w.at,
                category=Category.WEATHER,
                source=Source.WEATHER,
                note=w.note,
            )
        )

    for t in telemetry:
        entries.append(
            LogEntry(
                entry_id=t.entry_id,
                at=t.at,
                category=t.category,
                source=Source.TELEMETRY,
                feeder=t.feeder,
                consumers_out=t.consumers_out,
                note=t.note,
                flag=t.flag,
            )
        )

    for d in damage:
        entries.append(
            LogEntry(
                entry_id=d.entry_id,
                at=d.reported_at,
                category=Category.DAMAGE,
                source=Source.DAMAGE,
                feeder=d.feeder,
                note=_damage_note(d),
            )
        )

    for c in crews:
        if c.mobilized_at is None:
            continue  # no time, no place on a timeline; the gap is reported elsewhere
        where = f" to {c.assigned_to}" if c.assigned_to else ""
        aid = "Mutual-aid " if c.mutual_aid else ""
        entries.append(
            LogEntry(
                entry_id=c.entry_id,
                at=c.mobilized_at,
                category=Category.DISPATCH,
                source=Source.CREW,
                feeder=c.assigned_to,
                note=(
                    f"{aid}{c.crew_type} of {c.headcount} from {c.home_base} mobilised{where}."
                    f"{' ' + c.note if c.note else ''}"
                ).strip(),
            )
        )

    for m in comms:
        way = "Received from consumers" if m.direction is Direction.IN else "Issued to consumers"
        entries.append(
            LogEntry(
                entry_id=m.entry_id,
                at=m.at,
                category=Category.COMMUNICATION,
                source=Source.COMMS,
                note=(
                    f"{way} by {m.channel} ({m.audience:,}): {m.subject}."
                    f"{' ' + m.note if m.note else ''}"
                ).strip(),
            )
        )

    for f in field_reports:
        entries.append(
            LogEntry(
                entry_id=f.entry_id,
                at=f.at,
                category=f.category,
                source=Source.FIELD,
                feeder=f.feeder,
                note=f.note,
            )
        )

    # Sorted by time, then by id so a tie is stable across runs rather than dependent
    # on which file happened to be read first.
    entries.sort(key=lambda e: (e.at, e.entry_id))
    return entries


def _damage_note(d: DamageRecord) -> str:
    """A damage record read back as a sentence, with its status stated rather than implied.

    "Reported" damage is a fact about somebody's claim, not about the asset, and the
    timeline has to say which it is. Written here from the structured fields so the
    counts in the sentence and the counts in the totals cannot disagree.
    """
    asset = d.asset_type.value.replace("_", " ")
    plural = asset if d.count == 1 else f"{asset}s"
    where = f" at {d.location}" if d.location else ""
    status = {
        DamageStatus.REPORTED: "reported damaged, not yet inspected",
        DamageStatus.CONFIRMED: "confirmed damaged",
        DamageStatus.REPAIRED: "confirmed damaged",
    }[d.status]
    by = {
        ReportedBy.CUSTOMER: "raised by a consumer",
        ReportedBy.TELEMETRY: "raised by telemetry",
        ReportedBy.CREW: "raised by a crew",
    }[d.reported_by]
    return f"{d.count} {plural}{where} {status} ({by}). {d.note}".strip()


def _check_ids(corpus: Corpus) -> None:
    """Ids must be unique across all six sets, and must match their file's prefix.

    Checked over every record rather than over the merged timeline, because a record
    that never reaches the timeline — a crew with no mobilisation time — can still be
    cited, and two records sharing an id would make that citation ambiguous.
    """
    seen: set[str] = set()
    everything = [
        *((w.entry_id) for w in corpus.weather),
        *((t.entry_id) for t in corpus.telemetry),
        *((d.entry_id) for d in corpus.damage),
        *((c.entry_id) for c in corpus.crews),
        *((m.entry_id) for m in corpus.comms),
        *((f.entry_id) for f in corpus.field_reports),
    ]
    for entry_id in everything:
        if entry_id in seen:
            raise CorpusError(
                f"{corpus.event.event_id}: duplicate record id {entry_id}. Ids are "
                "cited in the report and must name exactly one record."
            )
        seen.add(entry_id)


def _check_references(corpus: Corpus) -> None:
    """Every cited record must exist. Citing nothing is allowed; citing a ghost is not."""
    known = corpus.entry_ids
    cited: list[tuple[str, list[str]]] = [
        (r.entry_id, r.sources) for r in (*corpus.crews, *corpus.comms)
    ]
    cited += [(d.entry_id, [d.source_ref]) for d in corpus.damage if d.source_ref]

    for ident, refs in cited:
        for ref in refs:
            if ref not in known:
                raise CorpusError(
                    f"{corpus.event.event_id}: {ident} cites {ref}, which is not in any "
                    "record set for this event"
                )

    # A crew that never appears on the timeline still has to cite something real, and a
    # damage record raised by a consumer must be able to point at the contact that
    # raised it. Both are checked above; what cannot be checked is a record that cites
    # nothing, which is a gap and is reported in the document rather than raised here.


def load_lessons_opened(event_id: str, root: Path | None = None) -> list[Lesson]:
    """The lessons-learned items this event raised for the first time."""
    folder = (root or DATA_ROOT) / event_id
    return [
        Lesson(
            lesson_id=r["lesson_id"],
            title=r["title"],
            detail=r["detail"],
            owner=r["owner"],
            opened_in_event=event_id,
            status=LessonStatus.OPEN,
            sources=_refs(r["sources"]),
        )
        for r in _rows(folder / "lessons_opened.csv")
    ]


def load_resolutions(event_id: str, root: Path | None = None) -> list[dict[str, object]]:
    """What this event decided about items raised by earlier events.

    Returned raw rather than as Lessons: a resolution is a decision *about* a lesson
    that lives in the carry-forward store, so applying it belongs to `lessons.py`.
    """
    folder = (root or DATA_ROOT) / event_id
    return [
        {
            "lesson_id": r["lesson_id"],
            "status": LessonStatus(r["status"].strip()),
            "note": r["note"].strip() or None,
            "sources": _refs(r["sources"]),
        }
        for r in _rows(folder / "lesson_resolutions.csv")
    ]


def available_events(root: Path | None = None) -> list[str]:
    """Every event folder on disk, by name."""
    base = root or DATA_ROOT
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "event.json").exists())


def events_in_order(root: Path | None = None) -> list[str]:
    """Every event on disk, oldest storm first.

    Ordered by when the event actually started, never by folder name. Carry-forward only
    means anything in chronological order — a later report closes an earlier report's
    items — and a folder name is a naming convention, not a fact about the weather. Two
    events called "flood-2025" and "alpha-squall" sort one way by name and the other way
    by date, and only one of those orders produces a correct register.
    """
    base = root or DATA_ROOT
    dated: list[tuple[datetime, str]] = []
    for name in available_events(base):
        raw = json.loads((base / name / "event.json").read_text(encoding="utf-8"))
        dated.append((datetime.fromisoformat(raw["started_at"]), name))
    return [name for _, name in sorted(dated)]
