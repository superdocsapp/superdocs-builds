from datetime import date

import pytest

from src.charts import render_trend_chart_png
from src.models import Assessment, Client


def test_chart_requires_at_least_two_assessments():
    client = Client(client_id="c1", display_name="X", goal="Y",
                     assessments=[Assessment(assessment_date=date(2025, 1, 1), values={"weight_kg": 80.0})])
    with pytest.raises(ValueError):
        render_trend_chart_png(client)


def test_chart_renders_valid_png_bytes():
    client = Client(client_id="c1", display_name="X", goal="Y", assessments=[
        Assessment(assessment_date=date(2025, 1, 1), values={"weight_kg": 80.0, "bench_1rm_kg": 50.0}),
        Assessment(assessment_date=date(2025, 3, 1), values={"weight_kg": 76.0, "bench_1rm_kg": 55.0}),
    ])
    png = render_trend_chart_png(client)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number -- it's a real image, not a stub
    assert len(png) > 1000  # sanity: not an empty/blank image


def test_chart_skips_metrics_with_only_one_data_point():
    client = Client(client_id="c1", display_name="X", goal="Y", assessments=[
        Assessment(assessment_date=date(2025, 1, 1), values={"weight_kg": 80.0}),
        Assessment(assessment_date=date(2025, 3, 1), values={"weight_kg": 76.0, "bench_1rm_kg": 55.0}),
    ])
    # bench_1rm_kg only has one data point across assessments -- should not error,
    # should just plot weight_kg alone.
    png = render_trend_chart_png(client)
    assert len(png) > 500
