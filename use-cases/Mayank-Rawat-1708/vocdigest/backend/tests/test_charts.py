"""
@file: backend/tests/test_charts.py
@description: Tests the chart renderers. The important assertions are not that markup is
    produced but that it is deterministic (charts must not break idempotency) and that
    charts are omitted rather than drawn misleadingly when the data does not support
    them.
@flow: build specs from theme dicts -> assert SVG and text output -> assert unmatched
    themes are excluded from comparison charts rather than plotted against zero.
@dependencies: backend.services.charts
"""

from __future__ import annotations

import pytest

from backend.services.charts import (
    ChartSpec,
    build_comparison_chart,
    build_growth_chart,
    build_volume_chart,
    chart_block,
    render_bar_chart_svg,
    render_bar_chart_text,
    render_comparison_text,
    render_sparkline_svg,
)

THEMES = [
    {"name": "Export silently fails", "volume_count": 60, "volume_share": 0.30,
     "prior_quarter_count": 38, "growth_rate": 0.579},
    {"name": "Dashboard loads slowly", "volume_count": 45, "volume_share": 0.225,
     "prior_quarter_count": 61, "growth_rate": -0.262},
    {"name": "Notification emails missing", "volume_count": 35, "volume_share": 0.175,
     "prior_quarter_count": 12, "growth_rate": 1.917},
    {"name": "iOS app crashes", "volume_count": 30, "volume_share": 0.15,
     "prior_quarter_count": None, "growth_rate": None},
]


def test_charts_are_deterministic():
    """Identical input must produce byte-identical markup.

    Charts are embedded in edit instructions, so non-determinism here would make a
    resumed run send a different instruction than the run it continues.
    """
    spec = build_volume_chart(THEMES)
    assert render_bar_chart_svg(spec) == render_bar_chart_svg(build_volume_chart(THEMES))
    assert render_bar_chart_text(spec) == render_bar_chart_text(build_volume_chart(THEMES))


def test_volume_chart_reflects_actual_numbers():
    spec = build_volume_chart(THEMES)
    assert [s.value for s in spec.series] == [60, 45, 35, 30]
    text = render_bar_chart_text(spec)
    assert "Export silently fails" in text and "60" in text
    # Longest bar belongs to the largest value.
    lines = [ln for ln in text.split("\n") if "│" in ln]
    assert lines[0].count("█") >= lines[-1].count("█")


def test_comparison_excludes_unmatched_themes():
    """A theme with no prior match must not be plotted against zero.

    Drawing it would turn "we have no comparison data" into the much stronger and
    unsupported claim "this went from nothing to thirty".
    """
    spec = build_comparison_chart(THEMES, "Q2 2026")
    names = [s.label for s in spec.series]
    assert "iOS app crashes" not in names
    assert all(s.prior is not None for s in spec.series)


def test_growth_chart_respects_threshold():
    spec = build_growth_chart(THEMES, threshold=0.25)
    names = [s.label for s in spec.series]
    assert "Notification emails missing" in names   # +192%
    assert "Export silently fails" in names          # +58%
    assert "Dashboard loads slowly" not in names     # shrank


def test_empty_data_produces_no_misleading_chart():
    assert build_growth_chart([], threshold=0.25).series == []
    assert build_comparison_chart([]).series == []
    assert "no data" in render_bar_chart_text(ChartSpec(title="Empty"))
    assert "no prior-quarter data" in render_comparison_text(ChartSpec(title="X"))


def test_svg_is_well_formed_and_escaped():
    hostile = [{"name": '<script>alert("x")</script>', "volume_count": 5,
                "volume_share": 0.1, "prior_quarter_count": None, "growth_rate": None}]
    svg = render_bar_chart_svg(build_volume_chart(hostile))
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    # A theme name is untrusted text that reached us from customer data.
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_chart_block_emits_both_renderings():
    """SVG plus a text fallback, because SVG survival through DOCX is unverified."""
    block = chart_block(build_volume_chart(THEMES))
    assert "<svg" in block
    assert "<pre>" in block and "█" in block


def test_sparkline_handles_flat_series():
    assert render_sparkline_svg([5, 5, 5, 5]).startswith("<svg")
    assert render_sparkline_svg([1]) == ""


@pytest.mark.asyncio
async def test_draft_includes_charts_when_comparison_available(
    test_db, fake_groq, fake_superdocs, sample_csv, prior_digest
):
    """The draft must actually carry chart instructions, not merely be able to."""
    from backend.agents.graph import create_run, execute_run, load_state

    run_uuid = await create_run(str(sample_csv), str(prior_digest))
    await execute_run(run_uuid)
    state = await load_state(run_uuid)

    sections = state["draft_sections"]
    assert "chart_volume" in sections
    assert "<svg" in sections["chart_volume"]
    assert "exactly as given" in sections["chart_volume"], (
        "the instruction must tell SuperDocs not to redraw the chart"
    )


@pytest.mark.asyncio
async def test_no_charts_without_comparison(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Without a prior quarter there must be no comparison or growth chart at all."""
    from backend.agents.graph import create_run, execute_run, load_state

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    state = await load_state(run_uuid)

    assert "chart_comparison" not in state["draft_sections"]
    assert "chart_growth" not in state["draft_sections"]
    assert any("comparison and growth charts were omitted" in w
               for w in state["draft_warnings"])
