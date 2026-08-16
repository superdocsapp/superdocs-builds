"""Read one event's three record sets off disk and cross-check them.

Loading is where the record sets stop being three separate CSVs and become one
corpus whose references either resolve or are reported. A crew record that cites a
log entry which does not exist is a data error and raises; a crew record that cites
nothing at all is a *gap*, which is legitimate and is carried forward as a finding
rather than an exception. Those two cases look similar and are not, and keeping them
apart is most of what this module does.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .models import Corpus, CrewRecord, CustomerComm, Event, Lesson, LessonStatus, LogEntry

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"


class CorpusError(Exception):
    """The records are internally inconsistent in a way no report can paper over."""


def _dt(value: str | None) -> datetime | None:
    value = (value or "").strip()
    return datetime.fromisoformat(value) if value else None


def _refs(value: str | None) -> list[str]:
    """Source lists are semicolon-separated so they survive CSV without quoting games."""
    return [r.strip() for r in (value or "").split(";") if r.strip()]


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

    log = [
        LogEntry(
            entry_id=r["entry_id"],
            at=_dt(r["at"]),
            category=r["category"],
            feeder=r["feeder"] or None,
            consumers_out=int(r["consumers_out"]) if r["consumers_out"].strip() else None,
            note=r["note"],
            flag=(r.get("flag") or "").strip() or None,
        )
        for r in _rows(folder / "event_log.csv")
    ]
    if not log:
        raise CorpusError(f"{event_id}: the event log is empty; there is nothing to report on")

    seen: set[str] = set()
    for entry in log:
        if entry.entry_id in seen:
            raise CorpusError(f"{event_id}: duplicate log entry id {entry.entry_id}")
        seen.add(entry.entry_id)

    out_of_order = [
        (a.entry_id, b.entry_id) for a, b in zip(log, log[1:]) if b.at < a.at
    ]
    if out_of_order:
        raise CorpusError(
            f"{event_id}: event log is not in chronological order at {out_of_order[0]}"
        )

    crews = [
        CrewRecord(
            crew_id=r["crew_id"],
            crew_type=r["crew_type"],
            home_base=r["home_base"],
            headcount=int(r["headcount"]),
            mobilized_at=_dt(r["mobilized_at"]),
            released_at=_dt(r["released_at"]),
            mutual_aid=r["mutual_aid"].strip().lower() == "true",
            sources=_refs(r["sources"]),
        )
        for r in _rows(folder / "crew_records.csv")
    ]

    comms = [
        CustomerComm(
            comm_id=r["comm_id"],
            sent_at=_dt(r["sent_at"]),
            channel=r["channel"],
            audience=int(r["audience"]),
            subject=r["subject"],
            sources=_refs(r["sources"]),
        )
        for r in _rows(folder / "customer_comms.csv")
    ]

    corpus = Corpus(event=event, log=log, crews=crews, comms=comms)
    _check_references(corpus)
    return corpus


def _check_references(corpus: Corpus) -> None:
    """Every cited log entry must exist. Citing nothing is allowed; citing a ghost is not."""
    known = corpus.entry_ids
    for record in (*corpus.crews, *corpus.comms):
        ident = getattr(record, "crew_id", None) or record.comm_id
        for ref in record.sources:
            if ref not in known:
                raise CorpusError(
                    f"{corpus.event.event_id}: {ident} cites {ref}, which is not in the event log"
                )


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
    base = root or DATA_ROOT
    return sorted(p.name for p in base.iterdir() if (p / "event.json").exists())
