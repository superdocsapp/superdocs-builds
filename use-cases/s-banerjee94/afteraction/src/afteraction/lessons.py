"""The carry-forward store.

This is the file that makes "open actions genuinely carry forward across two
consecutive event reports" true rather than claimed. Storm A writes its lessons here;
Storm B reads them, applies its own resolutions, and its report opens with those items
marked open or closed — because it read them, not because they were retyped.

Two properties this module is built to hold, both tested:

* **Idempotent.** Applying the same event twice leaves the store byte-identical.
  Without that, "run both twice" produces duplicates and the carry-forward is a
  coincidence of run order rather than a property.
* **Evidenced.** A resolution cites log entries from the event that resolved it, and
  those citations are checked against that event's log like any other claim. Closing
  an action is a claim about the world and gets the same scrutiny.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Corpus, Lesson, LessonStatus

DEFAULT_STORE = Path(__file__).resolve().parents[2] / "state" / "lessons.json"


class CarryForwardError(Exception):
    """A resolution refers to something the records cannot support."""


def load_store(path: Path | None = None) -> list[Lesson]:
    path = path or DEFAULT_STORE
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Lesson.model_validate(item) for item in raw.get("lessons", [])]


def save_store(lessons: list[Lesson], path: Path | None = None) -> Path:
    path = path or DEFAULT_STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "lessons": [json.loads(x.model_dump_json()) for x in sorted(lessons, key=lambda x: x.lesson_id)],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def apply_event(
    store: list[Lesson],
    corpus: Corpus,
    opened: list[Lesson],
    resolutions: list[dict[str, object]],
) -> list[Lesson]:
    """Fold one event's lessons and resolutions into the store.

    Returns a new list; the input is not mutated. Running this twice with the same
    inputs returns an equal store, which is what makes a re-run safe.
    """
    event_id = corpus.event.event_id
    by_id = {x.lesson_id: x.model_copy(deep=True) for x in store}

    # Items this event raised. Re-raising an existing item updates its text but never
    # resets a status a later event set.
    for lesson in opened:
        _check_sources(corpus, lesson.lesson_id, lesson.sources)
        if lesson.lesson_id in by_id:
            existing = by_id[lesson.lesson_id]
            existing.title = lesson.title
            existing.detail = lesson.detail
            existing.owner = lesson.owner
            existing.sources = lesson.sources
        else:
            by_id[lesson.lesson_id] = lesson.model_copy(deep=True)

    # Decisions this event took about items raised earlier.
    for res in resolutions:
        lesson_id = str(res["lesson_id"])
        target = by_id.get(lesson_id)
        if target is None:
            raise CarryForwardError(
                f"{event_id}: resolution names {lesson_id}, which no event has ever opened. "
                "A resolution cannot close an item that does not exist."
            )
        if target.opened_in_event == event_id:
            raise CarryForwardError(
                f"{event_id}: {lesson_id} was both opened and resolved by the same event"
            )
        sources = [str(s) for s in (res.get("sources") or [])]
        _check_sources(corpus, lesson_id, sources)
        note = res.get("note")
        target.last_reviewed_event = event_id

        if res["status"] is LessonStatus.CLOSED:
            target.status = LessonStatus.CLOSED
            target.closed_in_event = event_id
            target.closed_note = str(note) if note else None
            # The evidence that closed it lives in the closing event's log, not the
            # log of the event that raised it. Keeping them in separate fields is what
            # lets the report cite the right one.
            target.closed_sources = sources
            target.carry_note = None
            target.carry_sources = []
        else:
            target.status = LessonStatus.OPEN
            target.closed_in_event = None
            target.closed_note = None
            target.closed_sources = []
            target.carry_note = str(note) if note else None
            target.carry_sources = sources

    return sorted(by_id.values(), key=lambda x: x.lesson_id)


def _check_sources(corpus: Corpus, ident: str, sources: list[str]) -> None:
    unknown = [s for s in sources if s not in corpus.entry_ids]
    if unknown:
        raise CarryForwardError(
            f"{corpus.event.event_id}: {ident} cites {', '.join(unknown)}, which "
            f"{'is' if len(unknown) == 1 else 'are'} not in this event's log"
        )


def inherited(store: list[Lesson], event_id: str) -> list[Lesson]:
    """The items this event inherits — everything opened by an earlier event.

    This is what the Lessons Learned section of *this* event's report opens with.
    """
    return [x for x in store if x.opened_in_event != event_id]


def raised_here(store: list[Lesson], event_id: str) -> list[Lesson]:
    return [x for x in store if x.opened_in_event == event_id]


def summarise(store: list[Lesson], event_id: str) -> dict[str, int]:
    carried = inherited(store, event_id)
    return {
        "inherited": len(carried),
        "inherited_open": sum(1 for x in carried if x.status is LessonStatus.OPEN),
        "inherited_closed": sum(1 for x in carried if x.status is LessonStatus.CLOSED),
        "raised_here": len(raised_here(store, event_id)),
    }
