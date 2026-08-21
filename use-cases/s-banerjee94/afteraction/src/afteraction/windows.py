"""Group the timeline into fixed time windows, one bullet per window.

The problem this solves: the old timeline wrote one bullet per record. Thirty records
gave eighteen bullets, which reads well. Four thousand records — an ordinary number for
a real substation over a multi-day restoration — would give two thousand, and the
report becomes the log.

A commission wants roughly twenty milestones whether the log holds thirty lines or
thirty thousand. The output length is fixed by what a reader will read, so the funnel
has to absorb the growth instead.

The rule, and it is a rule rather than a judgement so that it can be stated in the
report and defended afterwards:

    event duration <= 16 hours   ->  one bullet per 1-hour window
    event duration >  16 hours   ->  one bullet per 2-hour window

Sixteen hours is where a storm stops being a shift and becomes a multi-day restoration:
crews stand down overnight, water has to recede, mutual aid travels. Past that point an
hour-by-hour account is mostly empty hours.

Windows are aligned to the clock, not to the event's start minute, so "18:00–20:00"
means what a reader expects rather than "17:43–19:43". Empty windows produce no bullet
at all — a quiet night is not eighteen bullets saying nothing happened.

Python decides the window and which records fall in it. The model is given one window's
records and asked to write two lines. It never chooses what is significant, because a
selection nobody can state is a selection nobody can defend to a regulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Category, Corpus, LogEntry

# Above this many hours, windows double. See the module docstring for why 16.
LONG_EVENT_HOURS = 16
SHORT_WINDOW_HOURS = 1
LONG_WINDOW_HOURS = 2

# Which categories belong on the narrative timeline. Communications have their own
# section and would otherwise crowd every window with message traffic; they are
# summarised there instead, in both directions.
TIMELINE_CATEGORIES = (
    Category.WEATHER,
    Category.OUTAGE,
    Category.DAMAGE,
    Category.DISPATCH,
    Category.RESTORATION,
    Category.SAFETY,
    Category.ACCESS,
    Category.ASSESSMENT,
)


@dataclass(frozen=True)
class Window:
    """One time window and the records that fall inside it."""

    start: datetime
    end: datetime
    entries: tuple[LogEntry, ...]

    @property
    def sources(self) -> list[str]:
        """Every record id in this window, in order. All of them go on the bullet."""
        return [e.entry_id for e in self.entries]

    @property
    def label(self) -> str:
        """How the window reads in the document.

        A window that stays inside one calendar day names the day once; one that crosses
        midnight names both, because "23:00–01:00" on its own is ambiguous about which
        night it means.
        """
        if self.start.date() == (self.end - timedelta(seconds=1)).date():
            return f"{self.start:%d %B}, {self.start:%H:%M}–{self.end:%H:%M}"
        return f"{self.start:%d %B %H:%M} – {self.end:%d %B %H:%M}"

    @property
    def peak_out(self) -> int | None:
        """The highest consumer count recorded inside this window, if any."""
        counts = [e.consumers_out for e in self.entries if e.consumers_out is not None]
        return max(counts) if counts else None


def window_hours(duration_hours: float) -> int:
    """The window size for an event of this length. The whole rule, in one place."""
    return LONG_WINDOW_HOURS if duration_hours > LONG_EVENT_HOURS else SHORT_WINDOW_HOURS


def _floor_to(moment: datetime, hours: int) -> datetime:
    """Snap down to the nearest clock-aligned window boundary."""
    return moment.replace(minute=0, second=0, microsecond=0, hour=(moment.hour // hours) * hours)


def build_windows(corpus: Corpus, categories: tuple[Category, ...] | None = None) -> list[Window]:
    """Bucket the timeline records into clock-aligned windows, skipping empty ones."""
    wanted = categories if categories is not None else TIMELINE_CATEGORIES
    entries = [e for e in corpus.log if e.category in set(wanted)]
    if not entries:
        return []

    size = window_hours(corpus.event.duration_hours)
    step = timedelta(hours=size)

    buckets: dict[datetime, list[LogEntry]] = {}
    for entry in entries:
        buckets.setdefault(_floor_to(entry.at, size), []).append(entry)

    return [
        Window(start=start, end=start + step, entries=tuple(buckets[start]))
        for start in sorted(buckets)
    ]


def coverage(corpus: Corpus, windows: list[Window]) -> tuple[int, int]:
    """How many timeline records went in, and how many bullets come out.

    Reported in the document so the compression is visible rather than implied: a reader
    who sees fourteen bullets is entitled to know they stand for sixty records.
    """
    entries = sum(len(w.entries) for w in windows)
    return entries, len(windows)
