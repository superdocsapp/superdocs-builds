"""Render the event's two charts as PNGs for embedding in the document.

The card asks for the restoration timeline as a diagram *inside* the document, so the
curve is rendered here and uploaded through the images endpoint; SuperDocs holds the
URL and the document references it.

Two charts, one visual system:

* **The restoration curve** — consumers without supply over time. Where the records
  declare that counting was interrupted, the line is broken and the window is shaded.
  Drawing a smooth line across a window with no data would assert a restoration
  trajectory nobody measured, which is precisely the kind of claim this build refuses
  to make.
* **The complaints chart** — consumer contacts received against contacts closed. The
  gap between the two lines is the backlog, and the shaded part of that gap is the
  portion open longer than the event's own target. A commission asks how many consumers
  called and how long they waited; a report with only outbound messages cannot answer.

Both use step lines rather than smooth ones. Counts change at the moment a batch
arrives or a feeder is re-energised, not continuously in between, and a smooth line
between two readings draws values nobody recorded.

The palette is the validated categorical trio — blue, aqua, orange — checked for
colour-vision separation and contrast rather than chosen by eye. Aqua sits below the
3:1 contrast floor on white, so every series is also directly labelled: identity is
never carried by colour alone.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in CI or on a build box

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .facts import FactSet, declared_count_gaps  # noqa: E402

# Text and furniture. Text never wears a series colour — a coloured mark beside a label
# carries identity, the label itself stays ink.
INK = "#1B2733"
MUTED = "#6D7886"
GRID = "#D8DEE5"

# The validated categorical trio. Slot order is fixed and never cycled.
SERIES_1 = "#2a78d6"  # blue   — the measured load
SERIES_2 = "#1baf7a"  # aqua   — the response
SERIES_3 = "#eb6834"  # orange — the problem: missing data, or a contact past target


def render_curve(facts: FactSet, out_path: Path) -> Path:
    """Draw consumers-out against time. Returns the path written."""
    readings = facts.readings
    if len(readings) < 2:
        raise ValueError("a restoration curve needs at least two consumer counts")

    gaps = declared_count_gaps(facts.corpus)
    event = facts.corpus.event

    # Split the series into runs separated by the declared gaps, so the line breaks
    # exactly where the data does.
    runs: list[list] = []
    current: list = []
    for reading in readings:
        if current and any(current[-1].at <= start.at and reading.at >= end.at for start, end in gaps):
            runs.append(current)
            current = []
        current.append(reading)
    if current:
        runs.append(current)

    # Wide and short. The curve sits inside a report that has to stay near two pages, and
    # a chart's height is page space; the shape it has to show is a decline over time,
    # which reads fine in a band.
    fig, ax = plt.subplots(figsize=(10, 3.1), dpi=160)

    for run in runs:
        if len(run) == 1:
            ax.plot([run[0].at], [run[0].consumers_out], marker="o", color=SERIES_1, markersize=4)
            continue
        xs = [r.at for r in run]
        ys = [r.consumers_out for r in run]
        ax.plot(xs, ys, color=SERIES_1, linewidth=2, marker="o", markersize=3.6, zorder=3)
        ax.fill_between(xs, ys, color=SERIES_1, alpha=0.10, zorder=1)

    # Label the gap vertically inside its own band: the band is narrow, and horizontal
    # text here would sit on top of the peak annotation.
    for start, end in gaps:
        ax.axvspan(start.at, end.at, color=SERIES_3, alpha=0.13, zorder=0)
        ax.text(
            start.at + (end.at - start.at) / 2,
            ax.get_ylim()[1] * 0.5,
            "no counts recorded",
            ha="center",
            va="center",
            rotation=90,
            fontsize=7.5,
            color=MUTED,
        )

    # Peak label sits to the left of its point, away from the gap band that follows it.
    peak = max(readings, key=lambda r: r.consumers_out)
    ax.annotate(
        f"peak {peak.consumers_out:,} out\n{peak.entry_id}",
        xy=(peak.at, peak.consumers_out),
        xytext=(-10, 4),
        textcoords="offset points",
        ha="right",
        fontsize=8,
        color=INK,
        linespacing=1.35,
    )

    ax.set_title(
        f"{event.name} — consumers without supply{_when(event)}",
        fontsize=11.5,
        color=INK,
        loc="left",
        pad=12,
    )
    ax.set_ylabel("consumers without supply", fontsize=9, color=INK)
    _furniture(ax, event)

    footnote = (
        f"Source: {event.substation or event.utility} telemetry, "
        f"{len(readings)} recorded counts"
        + (f"; {len(gaps)} declared interruption to counting" if gaps else "")
    )
    fig.text(0.008, 0.015, footnote, fontsize=7, color=MUTED)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path


def render_complaints(facts: FactSet, out_path: Path) -> Path | None:
    """Draw consumer contacts received against contacts closed.

    Returns None when the records hold no inbound contacts — an event nobody called
    about gets no chart rather than an empty one.
    """
    points = facts.complaints
    if len(points) < 2:
        return None

    event = facts.corpus.event
    xs = [p.at for p in points]
    received = [p.received for p in points]
    resolved = [p.resolved for p in points]
    late_top = [p.resolved + p.open_late for p in points]
    any_late = any(p.open_late for p in points)

    fig, ax = plt.subplots(figsize=(10, 3.1), dpi=160)

    # The backlog is the space between the two lines, so it is drawn as space rather
    # than as a third number competing with them.
    ax.fill_between(
        xs, resolved, received, step="post", color=SERIES_1, alpha=0.10, zorder=1,
        label="Open backlog",
    )

    # The part of that backlog which is past the event's own target. Drawn sitting on
    # the resolved line so it reads as a slice of the backlog, not a separate quantity.
    if any_late:
        ax.fill_between(
            xs, resolved, late_top, step="post", color=SERIES_3, alpha=0.30, zorder=2,
            label=f"Open past the {event.complaint_target_hours}-hour target",
        )

    ax.step(xs, received, where="post", color=SERIES_1, linewidth=2, zorder=4, label="Contacts received")
    ax.step(xs, resolved, where="post", color=SERIES_2, linewidth=2, zorder=4, label="Contacts resolved")

    # Direct labels on both lines. Aqua sits under the 3:1 contrast floor on white, so
    # the label is what carries its identity; the legend repeats it rather than
    # replacing it.
    #
    # An event where every contact was answered ends with both series on the same
    # value, and two labels at one point print on top of each other. When they are
    # close enough to collide, they are nudged apart — which is also the clearest way
    # to say "these two met".
    apart = 0 if not received[-1] else abs(received[-1] - resolved[-1]) / max(received[-1], 1)
    lift = 6 if apart < 0.05 else 0
    _end_label(ax, xs[-1], received[-1], f"{received[-1]:,} received", SERIES_1, dy=lift)
    _end_label(ax, xs[-1], resolved[-1], f"{resolved[-1]:,} resolved", SERIES_2, dy=-lift)

    ax.set_title(
        f"{event.name} — consumer contacts received and resolved{_when(event)}",
        fontsize=11.5,
        color=INK,
        loc="left",
        pad=12,
    )
    ax.set_ylabel("consumer contacts", fontsize=9, color=INK)
    _furniture(ax, event)
    # Lower right: both series are cumulative, so they climb to the top right and the
    # space beneath the resolved line at the right edge is the one region always clear
    # of marks. "upper left" put the legend on top of the received line.
    ax.legend(
        loc="lower right",
        fontsize=8,
        frameon=False,
        labelcolor=INK,
        handlelength=1.6,
        borderaxespad=0.8,
    )

    open_at_end = points[-1].received - points[-1].resolved
    footnote = (
        f"Source: {event.substation or event.utility} consumer contact records, "
        f"{len(facts.corpus.inbound)} inbound batches"
        + (f"; {open_at_end:,} contacts still open when the event closed" if open_at_end else "")
    )
    fig.text(0.008, 0.015, footnote, fontsize=7, color=MUTED)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path


def _when(event) -> str:
    """The date, appended to a title when the x-axis no longer carries it."""
    if event.started_at.date() != event.ended_at.date():
        return ""
    return f", {event.started_at:%d %B %Y}"


def _end_label(ax, x, y, text: str, colour: str, dy: float = 0) -> None:
    """A direct label at the end of a series, with its own mark beside it."""
    ax.plot([x], [y], marker="o", markersize=5, color=colour, zorder=5)
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(8, dy),
        textcoords="offset points",
        va="center",
        fontsize=8,
        color=INK,
    )


def _furniture(ax, event) -> None:
    """Recessive grid and axes, shared by both charts so they read as one system."""
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{int(v):,}")
    # An event inside one calendar day does not need the date on every tick — it is in
    # the title and the footnote, and repeating it twelve times is furniture, not
    # information. A multi-day event does need it, because 04:00 is otherwise ambiguous.
    same_day = event.started_at.date() == event.ended_at.date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if same_day else "%d %b\n%H:%M"))
    ax.set_ylim(bottom=0)
    ax.margins(x=0.06)
