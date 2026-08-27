import csv


def build_evidence_table_html(csv_path: str) -> str:
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    headers = [
        "Study ID",
        "Author (Year)",
        "Design",
        "N",
        "Intervention",
        "Comparator",
        "Primary Outcome",
        "Result",
    ]
    field_map = [
        "study_id",
        "author_year",
        "design",
        "n_participants",
        "intervention",
        "comparator",
        "primary_outcome",
        "result",
    ]

    html = ['<table style="border-collapse: collapse; width: 100%; font-size: 0.9em;">']
    html.append("<thead><tr>")
    for h in headers:
        html.append(
            f'<th style="border: 1px solid #333; padding: 6px; background: #f0f0f0; text-align: left;">{h}</th>'
        )
    html.append("</tr></thead><tbody>")

    for row in rows:
        html.append("<tr>")
        for field in field_map:
            value = row.get(field, "")
            html.append(
                f'<td style="border: 1px solid #333; padding: 6px;">{value}</td>'
            )
        html.append("</tr>")

    html.append("</tbody></table>")
    return "".join(html)


def build_search_strategy_html(csv_path: str) -> str:
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    html = ["<h3>Search Strategy Appendix</h3>"]
    for row in rows:
        html.append(
            f'<p><strong>{row["database"]}</strong> (run {row["date_run"]}, {row["hits"]} hits)</p>'
        )
        html.append(
            f'<p style="font-family: monospace; background: #f7f7f7; padding: 8px; border-radius: 4px;">{row["query"]}</p>'
        )
        html.append(f'<p><em>Filters: {row["filters"]}</em></p>')
    return "".join(html)


def build_risk_of_bias_html(csv_path: str) -> str:
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))

    color_map = {"Low": "#d4edda", "Some concerns": "#fff3cd", "High": "#f8d7da"}
    headers = [
        "Study ID",
        "Randomization",
        "Deviations",
        "Missing Data",
        "Outcome Measurement",
        "Selective Reporting",
        "Overall",
    ]
    field_map = [
        "study_id",
        "randomization",
        "deviations",
        "missing_data",
        "outcome_measurement",
        "selective_reporting",
        "overall",
    ]

    html = [
        '<h3>Risk of Bias Summary</h3><table style="border-collapse: collapse; width: 100%; font-size: 0.9em;">'
    ]
    html.append("<thead><tr>")
    for h in headers:
        html.append(
            f'<th style="border: 1px solid #333; padding: 6px; background: #f0f0f0;">{h}</th>'
        )
    html.append("</tr></thead><tbody>")

    for row in rows:
        html.append("<tr>")
        for field in field_map:
            value = row.get(field, "")
            bg = color_map.get(value, "#ffffff")
            html.append(
                f'<td style="border: 1px solid #333; padding: 6px; background: {bg};">{value}</td>'
            )
        html.append("</tr>")

    html.append("</tbody></table>")
    return "".join(html)


if __name__ == "__main__":
    print("=== Evidence table ===")
    print(build_evidence_table_html("../sample_data/extraction_sheet.csv")[:300], "...")
    print()
    print("=== Search strategy ===")
    print(build_search_strategy_html("../sample_data/search_strategy.csv")[:300], "...")
    print()
    print("=== Risk of bias ===")
    print(build_risk_of_bias_html("../sample_data/risk_of_bias.csv")[:300], "...")
