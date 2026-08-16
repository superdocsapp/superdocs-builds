from datetime import date
from html import escape
from app.models.field_report import FieldReportData


def build_daily_report_html(
    *,
    report: FieldReportData,
    photo_urls: list[str] | None = None,
    photo_captions: list[str] | None = None,
) -> str:
    photo_urls = photo_urls or []
    photo_captions = photo_captions or []
    project = escape(report.project or "Not reported")

    report_date = (
        report.report_date.isoformat()
        if report.report_date
        else "Not reported"
    )

    total_headcount = (
        str(report.total_headcount)
        if report.total_headcount is not None
        else "Not reported"
    )

    manpower_rows = ""

    if report.manpower:
        for entry in report.manpower:
            manpower_rows += f"""
            <tr>
                <td>{escape(entry.trade)}</td>
                <td>
                    {
                        escape(str(entry.headcount))
                        if entry.headcount is not None
                        else "Not reported"
                    }
                </td>
                <td>{escape(entry.notes or "-")}</td>
            </tr>
            """
    else:
        manpower_rows = """
        <tr>
            <td colspan="3">Not reported</td>
        </tr>
        """

    equipment_rows = ""

    if report.equipment:
        for entry in report.equipment:
            equipment_rows += f"""
            <tr>
                <td>{escape(entry.equipment)}</td>
                <td>{escape(entry.status or "Not reported")}</td>
                <td>{escape(entry.notes or "-")}</td>
            </tr>
            """
    else:
        equipment_rows = """
        <tr>
            <td colspan="3">Not reported</td>
        </tr>
        """

    work_rows = ""

    if report.work_by_area:
        for entry in report.work_by_area:
            work_rows += f"""
            <tr>
                <td>{escape(entry.area)}</td>
                <td>{escape(entry.work_performed)}</td>
                <td>{escape(entry.status or "-")}</td>
            </tr>
            """
    else:
        work_rows = """
        <tr>
            <td colspan="3">Not reported</td>
        </tr>
        """

    delay_rows = ""

    if report.delays:
        for delay in report.delays:
            duration = (
                f"{delay.duration_hours:g} hours"
                if delay.duration_hours is not None
                else "Not reported"
            )

            cause_label = (
                delay.cause_category.replace("_", " ").title()
                if delay.cause_category
                else "Not categorized"
            )

            delay_rows += f"""
            <tr>
                <td>{escape(delay.description)}</td>
                <td>{escape(duration)}</td>
                <td>{escape(cause_label)}</td>
            </tr>
            """
    else:
        delay_rows = """
        <tr>
            <td colspan="3">No delays were reported in the source notes.</td>
        </tr>
        """

    if report.safety_observations:
        safety_html = "<ul>"

        for observation in report.safety_observations:
            safety_html += (
                f"<li>{escape(observation)}</li>"
            )

        safety_html += "</ul>"
    else:
        safety_html = (
            "<p>No safety observations were reported "
            "in the source notes.</p>"
        )


    if photo_urls:
        photo_items = []

        for index, url in enumerate(photo_urls, start=1):
            caption = (
                photo_captions[index - 1]
                if index - 1 < len(photo_captions)
                else "Caption not available."
            )

            photo_items.append(
                f"""
                <div class="photo-page">
                    <img
                        src="{escape(url)}"
                        alt="Site photo {index}"
                        style="max-width:100%;"
                    />
                    <p>
                        <strong>Caption:</strong>
                        {escape(caption)}
                    </p>
                </div>
                """
            )

        photo_section = "\n".join(photo_items)
    else:
        photo_section = (
            "<p><strong>Site photos:</strong> None provided.</p>"
        )

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">

    <title>Daily Field Report</title>

    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 36px;
            color: #222;
        }}

        h1 {{
            text-align: center;
            margin-bottom: 6px;
        }}

        .subtitle {{
            text-align: center;
            color: #666;
            margin-bottom: 28px;
        }}

        h2 {{
            border-bottom: 2px solid #333;
            padding-bottom: 5px;
            margin-top: 28px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0;
        }}

        th,
        td {{
            border: 1px solid #999;
            padding: 8px;
            text-align: left;
        }}

        th {{
            background: #eee;
        }}

        .source-notes {{
            background: #f5f5f5;
            padding: 14px;
            white-space: pre-wrap;
        }}

        .photo-page {{
            margin-top: 24px;
            page-break-inside: avoid;
        }}
    </style>
</head>

<body>

    <h1>Daily Field Report</h1>

    <div class="subtitle">
        Construction Site Operations Report
    </div>

    <table>
        <tr>
            <th>Project</th>
            <td>{project}</td>
        </tr>

        <tr>
            <th>Report Date</th>
            <td>{report_date}</td>
        </tr>

        <tr>
            <th>Total Headcount</th>
            <td>{total_headcount}</td>
        </tr>
    </table>

    <h2>Manpower</h2>

    <table>
        <tr>
            <th>Trade / Crew</th>
            <th>Headcount</th>
            <th>Notes</th>
        </tr>

        {manpower_rows}
    </table>

    <h2>Equipment</h2>

    <table>
        <tr>
            <th>Equipment</th>
            <th>Status</th>
            <th>Notes</th>
        </tr>

        {equipment_rows}
    </table>

    <h2>Work Performed by Area</h2>

    <table>
        <tr>
            <th>Area</th>
            <th>Work Performed</th>
            <th>Status / Notes</th>
        </tr>

        {work_rows}
    </table>

    <h2>Weather</h2>

    <p>
        {escape(report.weather or "Not reported")}
    </p>

    <h2>Delays & Causes</h2>

    <table>
        <tr>
            <th>Delay</th>
            <th>Duration</th>
            <th>Cause Category</th>
        </tr>

        {delay_rows}
    </table>

    <h2>Safety Observations</h2>

    {safety_html}

    <h2>Source Field Notes</h2>

    <div class="source-notes">
        {escape(report.source_notes)}
    </div>

    <h2>Site Photos</h2>

    {photo_section}

</body>
</html>
"""