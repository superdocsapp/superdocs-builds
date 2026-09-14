from app.chart import render_usage_chart_svg


def test_chart_is_valid_svg_containing_both_numbers():
    svg = render_usage_chart_svg("Acme Renewals Inc.", entitlement_units=10_000, units_used=15_000)
    text = svg.decode("utf-8")

    assert text.startswith("<svg")
    assert text.strip().endswith("</svg>")
    assert "10,000" in text
    assert "15,000" in text
    assert "Acme Renewals Inc." in text


def test_overage_gets_a_distinct_bar_segment():
    over = render_usage_chart_svg("X", entitlement_units=10_000, units_used=15_000).decode("utf-8")
    clean = render_usage_chart_svg("X", entitlement_units=10_000, units_used=9_000).decode("utf-8")

    assert "over)" in over
    assert "over)" not in clean
    assert "#b3261e" in over  # the overage segment's fill color
    assert "#b3261e" not in clean


def test_zero_entitlement_does_not_divide_by_zero():
    svg = render_usage_chart_svg("X", entitlement_units=0, units_used=0)
    assert svg.startswith(b"<svg")
