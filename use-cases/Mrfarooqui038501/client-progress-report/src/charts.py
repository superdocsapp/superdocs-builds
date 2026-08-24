"""
Deterministic chart generation.

These charts are built directly from the same Assessment values that feed
the comparison table (see report_builder.build_comparison_table). Nothing
here is AI-generated or AI-estimated: matplotlib plots exactly the numbers
we already computed, so "charts match the table" (the card's own bar for
what strong looks like) is true by construction, not by hope.
"""
from __future__ import annotations

import io
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # headless, no display backend needed
import matplotlib.pyplot as plt

from .models import METRICS, Client


def render_trend_chart_png(client: Client, metric_keys: Optional[list[str]] = None) -> bytes:
    """Render a small-multiples trend chart for the given client's metrics.

    Returns raw PNG bytes. Caller is responsible for uploading/saving them.
    Raises ValueError if the client has fewer than 2 assessments (nothing to
    trend yet) so callers can't silently produce an empty chart.
    """
    if len(client.assessments) < 2:
        raise ValueError(
            f"{client.client_id} has only {len(client.assessments)} assessment(s); "
            "need at least 2 to plot a trend."
        )

    metrics_to_plot = metric_keys or [m[0] for m in METRICS]
    # Only plot metrics that actually have data across assessments.
    plottable = []
    for key in metrics_to_plot:
        dates, values = client.series(key)
        if len(values) >= 2:
            plottable.append((key, dates, values))

    if not plottable:
        raise ValueError(f"{client.client_id} has no metric with 2+ data points to plot.")

    n = len(plottable)
    cols = 2
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(8, 2.6 * rows), squeeze=False)

    label_by_key = {m[0]: (m[1], m[2]) for m in METRICS}

    for i, (key, dates, values) in enumerate(plottable):
        ax = axes[i // cols][i % cols]
        label, unit = label_by_key.get(key, (key, ""))
        ax.plot(dates, values, marker="o", linewidth=2)
        ax.set_title(f"{label} ({unit})", fontsize=10)
        ax.tick_params(axis="x", labelrotation=30, labelsize=7)
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(True, alpha=0.3)

    # Hide any unused subplot cells
    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")

    fig.suptitle(f"{client.display_name} — Trend since baseline", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()
