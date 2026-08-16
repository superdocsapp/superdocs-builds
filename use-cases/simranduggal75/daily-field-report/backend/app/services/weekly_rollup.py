"""
Weekly rollup: aggregates the persisted report.json files for one
project over a date range into a grounded progress summary and
recurring-delay-cause tally.

Deliberately pure aggregation, not an LLM summary: every number and
sentence here is computed directly from report.json fields, so there
is nothing to hallucinate. If the range has no data (or only one
report, for recurrence), that is stated explicitly rather than
invented.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

from app.services.report_intake import STORAGE_DIR
from app.services.report_store import read_report_json

ROLLUPS_DIR = Path("storage/rollups")

MIN_REPORTS_FOR_RECURRENCE = 2


def _load_candidate_reports(storage_dir: Path) -> list[dict]:
    """
    Every report dir under storage_dir that has a persisted
    report.json, paired with its metadata (for the resolved project/
    date, falling back to report.json's own fields for reports that
    predate the metadata index).
    """

    if not storage_dir.exists():
        return []

    candidates = []

    for report_dir in sorted(storage_dir.iterdir()):
        if not report_dir.is_dir():
            continue

        report_data = read_report_json(report_dir)

        if report_data is None:
            continue

        metadata_path = report_dir / "metadata.json"
        metadata = {}

        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}

        resolved_project = metadata.get("project") or report_data.get("project")
        resolved_date = metadata.get("report_date") or report_data.get("report_date")

        candidates.append(
            {
                "report_id": report_dir.name,
                "report_dir": report_dir,
                "project": resolved_project,
                "report_date": resolved_date,
                "report_data": report_data,
            }
        )

    return candidates


def _in_range(report_date_str: str | None, start: date, end: date) -> bool:
    if not report_date_str:
        return False

    try:
        report_date = date.fromisoformat(report_date_str)
    except ValueError:
        return False

    return start <= report_date <= end


def _ref(record: dict) -> dict:
    return {"report_id": record["report_id"], "report_date": record["report_date"]}


def build_weekly_rollup(
    *,
    project: str,
    start_date: date,
    end_date: date,
    storage_dir: Path | None = None,
) -> dict:
    storage_dir = storage_dir or STORAGE_DIR
    project_normalized = project.strip().lower()

    all_candidates = _load_candidate_reports(storage_dir)

    undated = [
        c
        for c in all_candidates
        if c["project"]
        and c["project"].strip().lower() == project_normalized
        and not c["report_date"]
    ]

    matched = [
        c
        for c in all_candidates
        if c["project"]
        and c["project"].strip().lower() == project_normalized
        and _in_range(c["report_date"], start_date, end_date)
    ]

    matched.sort(key=lambda c: (c["report_date"], c["report_id"]))

    result = {
        "project": project,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "report_count": len(matched),
        "excluded_undated_count": len(undated),
        "reports": [_ref(c) for c in matched],
    }

    if not matched:
        result["progress_summary"] = None
        result["recurring_delay_causes"] = []
        result["all_delay_causes"] = []
        result["grounding_note"] = (
            f"No processed reports found for project '{project}' between "
            f"{start_date.isoformat()} and {end_date.isoformat()}. "
            "No claims are made because there is nothing to support them."
        )
        return result

    # -----------------------------------------------------------------
    # Progress summary: grouped facts, each traceable to its source
    # report(s). Nothing here is generated - it's a regrouping of
    # fields already present in each report.json.
    # -----------------------------------------------------------------

    work_by_area: dict[str, list[dict]] = {}
    headcount_by_date = []
    safety_observations = []

    for record in matched:
        data = record["report_data"]
        ref = _ref(record)

        for entry in data.get("work_by_area", []):
            area = entry.get("area") or "Unspecified area"
            work_by_area.setdefault(area, []).append(
                {
                    **ref,
                    "work_performed": entry.get("work_performed"),
                    "status": entry.get("status"),
                }
            )

        if data.get("total_headcount") is not None:
            headcount_by_date.append(
                {**ref, "total_headcount": data["total_headcount"]}
            )

        for observation in data.get("safety_observations", []):
            safety_observations.append({**ref, "observation": observation})

    result["progress_summary"] = {
        "work_by_area": work_by_area,
        "headcount_by_date": headcount_by_date,
        "safety_observations": safety_observations,
    }

    # -----------------------------------------------------------------
    # Delay cause tally. "Recurring" means the category shows up in
    # 2+ DISTINCT reports, not just 2+ delay entries inside one report.
    # -----------------------------------------------------------------

    causes: dict[str, dict] = {}

    for record in matched:
        data = record["report_data"]
        ref = _ref(record)
        report_ids_seen_for_this_report: set[str] = set()

        for delay in data.get("delays", []):
            category = delay.get("cause_category") or "uncategorized"

            bucket = causes.setdefault(
                category,
                {"cause_category": category, "occurrences": [], "report_ids": set()},
            )
            bucket["occurrences"].append(
                {
                    **ref,
                    "description": delay.get("description"),
                    "duration_hours": delay.get("duration_hours"),
                }
            )
            bucket["report_ids"].add(record["report_id"])

    all_delay_causes = []

    for category, bucket in causes.items():
        all_delay_causes.append(
            {
                "cause_category": category,
                "occurrence_count": len(bucket["occurrences"]),
                "distinct_report_count": len(bucket["report_ids"]),
                "occurrences": bucket["occurrences"],
            }
        )

    all_delay_causes.sort(key=lambda c: c["distinct_report_count"], reverse=True)

    result["all_delay_causes"] = all_delay_causes

    if len(matched) < MIN_REPORTS_FOR_RECURRENCE:
        result["recurring_delay_causes"] = []
        result["recurrence_note"] = (
            f"Only {len(matched)} report(s) in range - recurrence needs at "
            f"least {MIN_REPORTS_FOR_RECURRENCE} to mean anything, so no "
            "cause is flagged as recurring."
        )
    else:
        result["recurring_delay_causes"] = [
            c
            for c in all_delay_causes
            if c["distinct_report_count"] >= MIN_REPORTS_FOR_RECURRENCE
        ]
        result["recurrence_note"] = None

    return result


def build_weekly_rollup_html(rollup: dict) -> str:
    project = escape(rollup["project"])
    start_date = escape(rollup["start_date"])
    end_date = escape(rollup["end_date"])

    if rollup["report_count"] == 0:
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Weekly Rollup - {project}</title></head>
<body>
<h1>Weekly Rollup: {project}</h1>
<p>{escape(start_date)} to {escape(end_date)}</p>
<p><strong>{escape(rollup["grounding_note"])}</strong></p>
</body>
</html>"""

    reports_list = "".join(
        f"<li>{escape(r['report_id'])} &mdash; {escape(r['report_date'] or 'undated')}</li>"
        for r in rollup["reports"]
    )

    work_sections = ""
    for area, entries in rollup["progress_summary"]["work_by_area"].items():
        rows = "".join(
            f"<li>{escape(e['work_performed'] or '')} "
            f"({escape(e.get('status') or 'status not reported')}) "
            f"&mdash; <em>report {escape(e['report_id'])}, "
            f"{escape(e['report_date'] or 'undated')}</em></li>"
            for e in entries
        )
        work_sections += f"<h3>{escape(area)}</h3><ul>{rows}</ul>"

    headcount_rows = "".join(
        f"<li>{escape(h['report_date'] or 'undated')}: {h['total_headcount']} "
        f"&mdash; <em>report {escape(h['report_id'])}</em></li>"
        for h in rollup["progress_summary"]["headcount_by_date"]
    )

    safety_rows = "".join(
        f"<li>{escape(s['observation'])} &mdash; "
        f"<em>report {escape(s['report_id'])}, {escape(s['report_date'] or 'undated')}</em></li>"
        for s in rollup["progress_summary"]["safety_observations"]
    )

    if rollup["recurring_delay_causes"]:
        recurring_rows = ""
        for cause in rollup["recurring_delay_causes"]:
            occ_rows = "".join(
                f"<li>{escape(o['description'] or '')} "
                f"&mdash; <em>report {escape(o['report_id'])}, "
                f"{escape(o['report_date'] or 'undated')}</em></li>"
                for o in cause["occurrences"]
            )
            label = escape(cause["cause_category"].replace("_", " ").title())
            recurring_rows += (
                f"<h3>{label} "
                f"(seen in {cause['distinct_report_count']} reports)</h3>"
                f"<ul>{occ_rows}</ul>"
            )
    else:
        note = rollup.get("recurrence_note") or "No delay cause recurred in this range."
        recurring_rows = f"<p><em>{escape(note)}</em></p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Weekly Rollup - {project}</title></head>
<body>
<h1>Weekly Rollup: {project}</h1>
<p>{start_date} to {end_date} &mdash; {rollup["report_count"]} report(s)</p>

<h2>Progress by Area</h2>
{work_sections or "<p><em>No work-by-area entries in this range.</em></p>"}

<h2>Headcount</h2>
<ul>{headcount_rows or "<li><em>No headcount reported in this range.</em></li>"}</ul>

<h2>Safety Observations</h2>
<ul>{safety_rows or "<li><em>No safety observations reported in this range.</em></li>"}</ul>

<h2>Recurring Delay Causes</h2>
{recurring_rows}

<h2>Supporting Daily Reports</h2>
<ul>{reports_list}</ul>
</body>
</html>"""


def save_weekly_rollup(
    *,
    project: str,
    start_date: date,
    end_date: date,
    storage_dir: Path | None = None,
    rollups_dir: Path | None = None,
) -> dict:
    rollup = build_weekly_rollup(
        project=project,
        start_date=start_date,
        end_date=end_date,
        storage_dir=storage_dir,
    )

    html = build_weekly_rollup_html(rollup)

    rollups_dir = rollups_dir or ROLLUPS_DIR
    rollups_dir.mkdir(parents=True, exist_ok=True)

    project_slug = "".join(
        ch if ch.isalnum() else "-" for ch in project.strip().lower()
    ).strip("-") or "project"

    base_name = f"{project_slug}_{start_date.isoformat()}_{end_date.isoformat()}"

    json_path = rollups_dir / f"{base_name}.json"
    html_path = rollups_dir / f"{base_name}.html"

    json_path.write_text(json.dumps(rollup, indent=2), encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    rollup["json_path"] = str(json_path)
    rollup["html_path"] = str(html_path)

    return rollup
