"""Tests for the post-edit verification step — confirms the pipeline can
actually detect a mismatch, not just report success optimistically."""

from techpack.verification import extract_measurement_table, verify_measurement_table


SAMPLE_STYLE = {
    "base_size": "M",
    "size_range": ["XS", "S", "M"],
    "measurement_points": [
        {"point_name": "Chest Width", "base_value": 20.0, "grade_rule": 1.0, "tolerance": 0.5},
    ],
}

CORRECT_HTML = """
<table>
  <tr><th>Point of Measure</th><th>XS</th><th>S</th><th>M</th><th>Tolerance</th></tr>
  <tr><td>Chest Width</td><td>18.0"</td><td>19.0"</td><td>20.0"</td><td>±0.5"</td></tr>
</table>
"""

WRONG_HTML = """
<table>
  <tr><th>Point of Measure</th><th>XS</th><th>S</th><th>M</th><th>Tolerance</th></tr>
  <tr><td>Chest Width</td><td>17.0"</td><td>19.0"</td><td>20.0"</td><td>±0.5"</td></tr>
</table>
"""

NO_TABLE_HTML = "<h1>Just a heading, no table at all</h1>"


def test_extract_measurement_table_parses_rows():
    rows = extract_measurement_table(CORRECT_HTML)
    assert rows[0] == ["Point of Measure", "XS", "S", "M", "Tolerance"]
    assert rows[1][0] == "Chest Width"


def test_verify_passes_on_correct_values():
    is_valid, mismatches = verify_measurement_table(CORRECT_HTML, SAMPLE_STYLE)
    assert is_valid is True
    assert mismatches == []


def test_verify_catches_a_single_wrong_value():
    # This is the case that matters most: one AI-mangled number in an
    # otherwise-correct table must not slip through silently
    is_valid, mismatches = verify_measurement_table(WRONG_HTML, SAMPLE_STYLE)
    assert is_valid is False
    assert any("Chest Width" in m and "XS" in m for m in mismatches)


def test_verify_fails_gracefully_when_table_missing():
    is_valid, mismatches = verify_measurement_table(NO_TABLE_HTML, SAMPLE_STYLE)
    assert is_valid is False
    assert len(mismatches) > 0