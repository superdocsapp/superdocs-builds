"""Usage-vs-entitlement chart for the renewal pack - a real image, not a text stand-in, closing the
`images` surface named on this build's card (SURFACES IT TOUCHES: ..., images, ...) alongside the pack's
existing 'usage and value summary from product data' section. Plain SVG, hand-built with string formatting
- no charting dependency, matching this project's minimal footprint (requirements.txt has no drawing
library, and adding matplotlib/Pillow for two bars would be a heavy answer to a small problem).
"""

from __future__ import annotations

_WIDTH = 420
_HEIGHT = 220
_BAR_WIDTH = 90
_CHART_TOP = 30
_CHART_BOTTOM = 170
_CHART_HEIGHT = _CHART_BOTTOM - _CHART_TOP


def _bar_height(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return (value / max_value) * _CHART_HEIGHT


def render_usage_chart_svg(customer_name: str, entitlement_units: float, units_used: float) -> bytes:
    """Two bars: contracted entitlement vs. actual usage this period. Overage (usage past entitlement) is
    drawn as a distinct top segment on the usage bar, so the chart shows the same overage the true-up math
    is charging for - not a generic pair of bars disconnected from the number the customer actually sees."""
    max_value = max(entitlement_units, units_used, 1.0) * 1.15  # headroom so the taller bar isn't clipped

    entitlement_h = _bar_height(entitlement_units, max_value)
    entitlement_y = _CHART_BOTTOM - entitlement_h

    usage_capped = min(units_used, entitlement_units)
    overage = max(0.0, units_used - entitlement_units)
    usage_capped_h = _bar_height(usage_capped, max_value)
    overage_h = _bar_height(overage, max_value)
    usage_y = _CHART_BOTTOM - usage_capped_h - overage_h

    entitlement_x = 90
    usage_x = 240

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" height="{_HEIGHT}" viewBox="0 0 {_WIDTH} {_HEIGHT}">
  <rect width="{_WIDTH}" height="{_HEIGHT}" fill="#ffffff"/>
  <text x="20" y="20" font-family="sans-serif" font-size="13" font-weight="700" fill="#17181c">{customer_name} - usage vs. entitlement</text>
  <line x1="40" y1="{_CHART_BOTTOM}" x2="400" y2="{_CHART_BOTTOM}" stroke="#c9c9cf" stroke-width="1"/>

  <rect x="{entitlement_x}" y="{entitlement_y:.1f}" width="{_BAR_WIDTH}" height="{entitlement_h:.1f}" fill="#5b5ee8" rx="3"/>
  <text x="{entitlement_x + _BAR_WIDTH / 2:.0f}" y="{entitlement_y - 8:.1f}" font-family="sans-serif" font-size="12" text-anchor="middle" fill="#17181c">{entitlement_units:,.0f}</text>
  <text x="{entitlement_x + _BAR_WIDTH / 2:.0f}" y="{_CHART_BOTTOM + 18}" font-family="sans-serif" font-size="11" text-anchor="middle" fill="#6b6f76">Entitlement</text>

  <rect x="{usage_x}" y="{usage_y:.1f}" width="{_BAR_WIDTH}" height="{usage_capped_h:.1f}" fill="#1e7a34" rx="3"/>
  {f'<rect x="{usage_x}" y="{usage_y:.1f}" width="{_BAR_WIDTH}" height="{overage_h:.1f}" fill="#b3261e" rx="3"/>' if overage > 0 else ""}
  <text x="{usage_x + _BAR_WIDTH / 2:.0f}" y="{usage_y - 8:.1f}" font-family="sans-serif" font-size="12" text-anchor="middle" fill="#17181c">{units_used:,.0f}{f" (+{overage:,.0f} over)" if overage > 0 else ""}</text>
  <text x="{usage_x + _BAR_WIDTH / 2:.0f}" y="{_CHART_BOTTOM + 18}" font-family="sans-serif" font-size="11" text-anchor="middle" fill="#6b6f76">Actual usage</text>
</svg>"""
    return svg.encode("utf-8")
