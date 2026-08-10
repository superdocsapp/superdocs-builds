"""Verifies that measurement numbers survived an AI edit unchanged.
Never trust the model's own claim ('wording unchanged') — check the actual HTML."""

import re
from techpack.grading import build_graded_spec


def extract_measurement_table(html: str) -> list[list[str]]:
    """Pulls raw cell text out of the first <table> in the HTML (the measurement table)."""
    table_match = re.search(r"<table.*?>(.*?)</table>", html, re.DOTALL)
    if not table_match:
        return []

    table_html = table_match.group(1)
    rows = re.findall(r"<tr.*?>(.*?)</tr>", table_html, re.DOTALL)

    parsed_rows = []
    for row in rows:
        cells = re.findall(r"<t[dh].*?>(.*?)</t[dh]>", row, re.DOTALL)
        cleaned = [re.sub(r"<.*?>", "", c).strip() for c in cells]
        parsed_rows.append(cleaned)

    return parsed_rows


def verify_measurement_table(html: str, style: dict) -> tuple[bool, list[str]]:
    """
    Compares the measurement values actually present in the HTML against
    the deterministically graded values. Returns (is_valid, list_of_mismatches).
    """
    graded = build_graded_spec(style)
    sizes = style["size_range"]
    rows = extract_measurement_table(html)

    if not rows or len(rows) < 2:
        return False, ["No measurement table found in HTML — cannot verify."]

    data_rows = rows[1:]  # skip header row
    expected_points = [p["point_name"] for p in style["measurement_points"]]

    mismatches = []
    found_points = {row[0] for row in data_rows if row}

    for point in expected_points:
        if point not in found_points:
            mismatches.append(f"MISSING: '{point}' row not found in table at all.")

    for row in data_rows:
        if not row:
            continue
        point_name = row[0]
        if point_name not in expected_points:
            continue  # some other row, e.g. from a merged/extra table — not our concern here

        for i, size in enumerate(sizes):
            cell_index = i + 1
            if cell_index >= len(row):
                mismatches.append(f"MISSING VALUE: '{point_name}' has no cell for size {size}")
                continue

            expected_val = graded[point_name][size]
            actual_cell = row[cell_index].replace('"', "").strip()

            try:
                actual_val = float(actual_cell)
            except ValueError:
                mismatches.append(
                    f"UNPARSEABLE: '{point_name}' at {size} — got '{actual_cell}', expected {expected_val}"
                )
                continue

            if abs(actual_val - expected_val) > 0.001:
                mismatches.append(
                    f"MISMATCH: '{point_name}' at {size} — expected {expected_val}, got {actual_val}"
                )

    return len(mismatches) == 0, mismatches