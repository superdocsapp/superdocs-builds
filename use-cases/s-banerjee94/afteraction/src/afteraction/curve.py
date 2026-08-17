"""Render the restoration curve as a PNG for embedding in the document.

The card asks for the restoration timeline as a diagram *inside* the document, so the
curve is rendered here and uploaded through the images endpoint; SuperDocs holds the
URL and the document references it.

The one visual decision that carries meaning: where the records declare that counting
was interrupted, the line is broken and the window is shaded. Drawing a smooth line
across a window with no data would assert a restoration trajectory nobody measured,
which is precisely the kind of claim this build refuses to make.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in CI or on a build box

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .facts import FactSet, declared_count_gaps  # noqa: E402

INK = "#1B2733"
GRID = "#D8DEE5"
LINE = "#1F5F73"
FILL = "#1F5F73"
GAPC = "#A6521C"
PEAK = "#8F2B2B"


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
            ax.plot([run[0].at], [run[0].consumers_out], marker="o", color=LINE, markersize=4)
            continue
        xs = [r.at for r in run]
        ys = [r.consumers_out for r in run]
        ax.plot(xs, ys, color=LINE, linewidth=2.1, marker="o", markersize=3.6, zorder=3)
        ax.fill_between(xs, ys, color=FILL, alpha=0.10, zorder=1)

    # Label the gap vertically inside its own band: the band is narrow, and horizontal
    # text here would sit on top of the peak annotation.
    for start, end in gaps:
        ax.axvspan(start.at, end.at, color=GAPC, alpha=0.13, zorder=0)
        ax.text(
            start.at + (end.at - start.at) / 2,
            ax.get_ylim()[1] * 0.5,
            "no counts recorded",
            ha="center",
            va="center",
            rotation=90,
            fontsize=7.5,
            color=GAPC,
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
        color=PEAK,
        linespacing=1.35,
    )

    ax.set_title(
        f"{event.name} — consumers without supply",
        fontsize=11.5,
        color=INK,
        loc="left",
        pad=12,
    )
    ax.set_ylabel("consumers without supply", fontsize=9, color=INK)
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK, labelsize=8)
    ax.yaxis.set_major_formatter(lambda v, _: f"{int(v):,}")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    ax.set_ylim(bottom=0)

    footnote = (
        f"Source: {event.utility} event log, {len(readings)} recorded counts"
        + (f"; {len(gaps)} declared interruption to counting" if gaps else "")
    )
    fig.text(0.008, 0.015, footnote, fontsize=7, color="#6D7886")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)
    return out_path
