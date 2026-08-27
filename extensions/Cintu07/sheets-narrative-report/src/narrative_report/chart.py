"""Render the selected range as a chart.

Two properties matter here and neither is aesthetic:

* The chart is drawn from the same :class:`~narrative_report.facts.Table` the
  prose is drawn from, so the picture and the sentences cannot disagree.
* :func:`chart_digest` hashes the *inputs*, not the rendered PNG. Image encoders
  embed timestamps and version strings, so identical data can produce different
  bytes; hashing the data is what makes "the chart did not change" a fact rather
  than a coin flip.
"""

from __future__ import annotations

import hashlib
import io
import json
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")  # no display, no interactive backend, safe on a server
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .facts import Series, Table  # noqa: E402

MAX_SERIES = 5
PALETTE = ["#1f4e79", "#c55a11", "#548235", "#7030a0", "#bf8f00"]


def choose_series(table: Table) -> list[Series]:
    """Pick what to plot.

    Currency lines are what a finance reader came for, so they win. Mixing units
    on one axis would make the chart misleading, so we never do it.
    """
    currency = [s for s in table.series if s.unit == "currency" and s.present]
    pool = currency or [s for s in table.series if s.unit == "number" and s.present]
    return sorted(pool, key=lambda s: max(abs(v) for v in s.present), reverse=True)[:MAX_SERIES]


def chart_digest(table: Table) -> str:
    """Stable hash of everything that determines the chart's appearance."""
    payload = {
        "periods": table.periods,
        "series": [
            {"label": s.label, "values": [None if v is None else str(v) for v in s.values]}
            for s in choose_series(table)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _axis_formatter(values: list[Decimal]) -> FuncFormatter:
    peak = max((abs(v) for v in values), default=Decimal(0))
    if peak >= 1_000_000:
        return FuncFormatter(lambda x, _: f"{x / 1_000_000:,.1f}M")
    if peak >= 1_000:
        return FuncFormatter(lambda x, _: f"{x / 1_000:,.0f}K")
    return FuncFormatter(lambda x, _: f"{x:,.0f}")


def render_chart(table: Table, *, title: str | None = None, width_px: int = 1200) -> bytes:
    """Draw the selection and return PNG bytes.

    Raises :class:`ValueError` when there is nothing plottable, rather than
    emitting an empty chart that would imply the data was flat.
    """
    series = choose_series(table)
    if not series:
        raise ValueError("no numeric series in the selection to plot")

    dpi = 150
    fig, ax = plt.subplots(figsize=(width_px / dpi, width_px * 0.45 / dpi), dpi=dpi)

    x = range(len(table.periods))
    all_values: list[Decimal] = []
    for index, s in enumerate(series):
        ys = [float(v) if v is not None else float("nan") for v in s.values]
        all_values += s.present
        ax.plot(
            list(x),
            ys,
            marker="o",
            markersize=4,
            linewidth=2,
            color=PALETTE[index % len(PALETTE)],
            label=s.label,
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels(table.periods, fontsize=9)
    ax.yaxis.set_major_formatter(_axis_formatter(all_values))
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(axis="y", linestyle=":", linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    if any(v < 0 for v in all_values):
        ax.axhline(0, color="#888888", linewidth=0.8)
    if title:
        ax.set_title(title, fontsize=11, loc="left", pad=10)
    if len(series) > 1:
        ax.legend(frameon=False, fontsize=9, ncol=min(len(series), 3))

    fig.tight_layout()
    buffer = io.BytesIO()
    # Suppress the Software tag so repeat renders differ only when data differs.
    fig.savefig(buffer, format="png", metadata={"Software": None})
    plt.close(fig)
    return buffer.getvalue()


def chart_html(url: str, alt: str) -> str:
    """The ``<img>`` block as it goes into the document."""
    escaped = alt.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    return (
        f'<p class="report-chart"><img src="{url}" alt="{escaped}" '
        'style="width:100%;max-width:680px;height:auto;" /></p>'
    )
