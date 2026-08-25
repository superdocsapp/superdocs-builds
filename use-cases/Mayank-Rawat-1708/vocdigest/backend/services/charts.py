"""
@file: backend/services/charts.py
@description: Renders the digest's trend visuals. Produces two forms of every chart: an
    inline SVG for HTML and PDF export, and a Unicode block-character version that
    survives any export format including plain text and Markdown. The dual output exists
    because SVG support through a DOCX round-trip is not something I could verify, and a
    chart that silently vanishes is worse than one that is merely plain.
@flow: theme rows -> ChartSpec (labels, values, optional comparison series) ->
    render_*_svg() emits standalone SVG markup, render_*_text() emits block characters ->
    the draft node embeds both in a SuperDocs edit instruction so whichever survives the
    target format is present.
@dependencies: none — deliberately dependency-free and deterministic, so the same data
    always produces byte-identical markup and charts never break idempotency.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

# Brand palette. Fixed rather than generated so repeated runs produce identical markup.
COLOR_PRIMARY = "#2563EB"
COLOR_GROWTH = "#DC2626"
COLOR_DECLINE = "#059669"
COLOR_NEUTRAL = "#94A3B8"
COLOR_PRIOR = "#CBD5E1"
COLOR_TEXT = "#0F172A"
COLOR_MUTED = "#64748B"
COLOR_GRID = "#E2E8F0"

# Full and partial block characters, eighths. Used by the text renderer so a bar has
# roughly eight times the resolution a whole-character bar would.
_EIGHTHS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"]
_FULL = "█"


@dataclass(slots=True)
class Series:
    """One bar in a chart."""

    label: str
    value: float
    prior: float | None = None
    color: str = COLOR_PRIMARY
    note: str = ""


@dataclass(slots=True)
class ChartSpec:
    """Everything needed to draw one chart, in both output forms."""

    title: str
    series: list[Series] = field(default_factory=list)
    value_suffix: str = ""
    caption: str = ""

    @property
    def max_value(self) -> float:
        candidates = [s.value for s in self.series]
        candidates += [s.prior for s in self.series if s.prior is not None]
        return max(candidates) if candidates else 0.0


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _fmt(value: float) -> str:
    """Whole numbers without a decimal point; fractions to one place."""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


# ---------------------------------------------------------------- text renderer


def render_bar_chart_text(spec: ChartSpec, width: int = 40) -> str:
    """Bar chart in Unicode block characters.

    Renders in every export format SuperDocs offers, including plain text and Markdown,
    which is why it is always emitted alongside the SVG rather than as a fallback that
    only appears when something fails.
    """
    if not spec.series:
        return f"{spec.title}\n(no data)"

    max_value = spec.max_value or 1.0
    label_width = min(max(len(s.label) for s in spec.series), 28)

    lines = [spec.title, ""]
    for s in spec.series:
        label = s.label[:label_width].ljust(label_width)
        filled = (s.value / max_value) * width
        whole = int(filled)
        remainder = int((filled - whole) * 8)
        bar = _FULL * whole + _EIGHTHS[remainder]
        value = f"{_fmt(s.value)}{spec.value_suffix}"

        if s.prior is not None:
            delta = s.value - s.prior
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "="
            trailer = f"  ({_fmt(s.prior)} {arrow} {_fmt(s.value)})"
        else:
            trailer = f"  ({s.note})" if s.note else ""

        lines.append(f"{label} │ {bar.ljust(width)} {value}{trailer}")

    if spec.caption:
        lines += ["", spec.caption]
    return "\n".join(lines)


def render_comparison_text(spec: ChartSpec, width: int = 30) -> str:
    """Two-row-per-theme prior/current comparison in block characters."""
    comparable = [s for s in spec.series if s.prior is not None]
    if not comparable:
        return f"{spec.title}\n(no prior-quarter data to compare against)"

    max_value = spec.max_value or 1.0
    lines = [spec.title, ""]
    for s in comparable:
        lines.append(s.label)
        for tag, value in (("prior  ", s.prior), ("current", s.value)):
            filled = int((value / max_value) * width)
            lines.append(f"  {tag} │ {(_FULL * filled).ljust(width)} {_fmt(value)}")
        delta = s.value - (s.prior or 0)
        pct = (delta / s.prior * 100) if s.prior else 0.0
        lines.append(f"  change  {'+' if delta > 0 else ''}{_fmt(delta)} ({pct:+.0f}%)")
        lines.append("")

    if spec.caption:
        lines.append(spec.caption)
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------- svg renderers


def render_bar_chart_svg(spec: ChartSpec, width: int = 640) -> str:
    """Horizontal bar chart as standalone inline SVG.

    Fixed geometry and no external fonts, so the markup is deterministic and self
    contained — nothing to fetch at render time.
    """
    if not spec.series:
        return ""

    row_height, gap, label_width, pad_top, pad_bottom = 28, 8, 190, 44, 28
    plot_width = width - label_width - 90
    height = pad_top + len(spec.series) * (row_height + gap) + pad_bottom
    max_value = spec.max_value or 1.0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="{_esc(spec.title)}" font-family="Inter, Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        f'<text x="16" y="26" font-size="15" font-weight="600" '
        f'fill="{COLOR_TEXT}">{_esc(spec.title)}</text>',
    ]

    # Quarter gridlines, drawn behind the bars.
    for i in range(1, 5):
        x = label_width + (plot_width * i / 4)
        parts.append(
            f'<line x1="{x:.1f}" y1="{pad_top - 6}" x2="{x:.1f}" '
            f'y2="{height - pad_bottom + 4}" stroke="{COLOR_GRID}" stroke-width="1"/>'
        )

    for index, s in enumerate(spec.series):
        y = pad_top + index * (row_height + gap)
        bar_width = max((s.value / max_value) * plot_width, 1.0)
        label = s.label if len(s.label) <= 26 else s.label[:25] + "…"

        parts.append(
            f'<text x="{label_width - 10}" y="{y + 18}" font-size="12" '
            f'text-anchor="end" fill="{COLOR_TEXT}">{_esc(label)}</text>'
        )

        # Prior-quarter bar sits behind the current one so the delta reads as growth.
        if s.prior is not None and s.prior > 0:
            prior_width = max((s.prior / max_value) * plot_width, 1.0)
            parts.append(
                f'<rect x="{label_width}" y="{y + 3}" width="{prior_width:.1f}" '
                f'height="{row_height - 6}" fill="{COLOR_PRIOR}" rx="3"/>'
            )
            parts.append(
                f'<rect x="{label_width}" y="{y + 7}" width="{bar_width:.1f}" '
                f'height="{row_height - 14}" fill="{s.color}" rx="3"/>'
            )
        else:
            parts.append(
                f'<rect x="{label_width}" y="{y + 4}" width="{bar_width:.1f}" '
                f'height="{row_height - 8}" fill="{s.color}" rx="3"/>'
            )

        value_text = f"{_fmt(s.value)}{spec.value_suffix}"
        parts.append(
            f'<text x="{label_width + bar_width + 8:.1f}" y="{y + 18}" font-size="12" '
            f'font-weight="600" fill="{COLOR_TEXT}">{_esc(value_text)}</text>'
        )

    if spec.caption:
        parts.append(
            f'<text x="16" y="{height - 10}" font-size="10" '
            f'fill="{COLOR_MUTED}">{_esc(spec.caption)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_sparkline_svg(values: list[float], width: int = 120, height: int = 28) -> str:
    """Small trend line. Flat when every value is equal, rather than dividing by zero."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 4 - ((v - lo) / span) * (height - 8):.1f}"
        for i, v in enumerate(values)
    )
    rising = values[-1] >= values[0]
    color = COLOR_GROWTH if rising else COLOR_DECLINE
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="trend">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


# ---------------------------------------------------------------- spec builders


def build_volume_chart(themes: list[dict], limit: int = 10) -> ChartSpec:
    """Theme volume ranked descending."""
    top = sorted(themes, key=lambda t: t.get("volume_count", 0), reverse=True)[:limit]
    return ChartSpec(
        title="Conversation volume by theme",
        series=[
            Series(
                label=t.get("name", "unnamed"),
                value=float(t.get("volume_count", 0)),
                color=COLOR_PRIMARY,
                note=f"{round(float(t.get('volume_share', 0)) * 100, 1)}% of volume",
            )
            for t in top
        ],
        caption=f"Top {len(top)} of {len(themes)} themes by conversation count.",
    )


def build_comparison_chart(themes: list[dict], prior_label: str = "last quarter") -> ChartSpec:
    """Prior vs current volume, only for themes that actually matched.

    Themes with no prior match are excluded rather than shown against zero, which would
    misrepresent "we have no data" as "this went from nothing".
    """
    matched = [
        t for t in themes
        if t.get("prior_quarter_count") is not None and t.get("prior_quarter_count") > 0
    ]
    matched.sort(key=lambda t: abs(float(t.get("growth_rate") or 0)), reverse=True)

    series = []
    for t in matched[:8]:
        growth = float(t.get("growth_rate") or 0)
        color = COLOR_GROWTH if growth > 0.15 else COLOR_DECLINE if growth < -0.15 else COLOR_NEUTRAL
        series.append(
            Series(
                label=t.get("name", "unnamed"),
                value=float(t.get("volume_count", 0)),
                prior=float(t["prior_quarter_count"]),
                color=color,
            )
        )

    return ChartSpec(
        title=f"Volume change vs {prior_label}",
        series=series,
        caption=(
            "Pale bar is the prior quarter, solid bar is this quarter. "
            "Only themes matched across both quarters appear here."
        ),
    )


def build_growth_chart(themes: list[dict], threshold: float = 0.25) -> ChartSpec:
    """Fastest-growing themes by percentage change."""
    growing = [
        t for t in themes
        if t.get("growth_rate") is not None and float(t["growth_rate"]) >= threshold
    ]
    growing.sort(key=lambda t: float(t["growth_rate"]), reverse=True)

    return ChartSpec(
        title="Fastest-growing issues",
        series=[
            Series(
                label=t.get("name", "unnamed"),
                value=round(float(t["growth_rate"]) * 100, 1),
                color=COLOR_GROWTH,
                note=f"{t.get('prior_quarter_count')} → {t.get('volume_count')}",
            )
            for t in growing[:8]
        ],
        value_suffix="%",
        caption=f"Themes growing more than {round(threshold * 100)}% quarter over quarter.",
    )


def chart_block(spec: ChartSpec, *, include_svg: bool = True) -> str:
    """Both renderings of one chart, ready to drop into an edit instruction.

    The text version is wrapped in <pre> so whitespace is preserved wherever the
    document lands. Both are emitted because SVG survival through a DOCX round-trip is
    not something I could confirm, and a missing chart is worse than a plain one.
    """
    text = render_bar_chart_text(spec)
    if not include_svg:
        return f"<pre>{_esc(text)}</pre>"
    svg = render_bar_chart_svg(spec)
    return f"{svg}\n<pre>{_esc(text)}</pre>" if svg else f"<pre>{_esc(text)}</pre>"
