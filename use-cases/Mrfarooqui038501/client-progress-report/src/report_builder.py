"""
Builds the deterministic and narrative parts of Client Progress Reports.

Deterministic content:
    - baseline facts
    - comparison table
    - adherence
    - chart

Narrative content:
    - what changed and why
    - next block's goals

Numerical values are supplied directly from Assessment objects.
The AI is never asked to calculate measurement changes.
"""

from __future__ import annotations

from html import escape

from .models import METRICS, Client


def _delta_str(
    baseline: float,
    current: float,
    higher_is_better: bool,
) -> str:
    """Return a human-readable change string."""

    diff = round(current - baseline, 1)

    if diff == 0:
        return "no change"

    sign = "+" if diff > 0 else ""

    good = (diff > 0) == higher_is_better

    arrow = "\u2191" if diff > 0 else "\u2193"

    tag = "improved" if good else "regressed"

    return f"{sign}{diff} {arrow} ({tag})"


# Metrics where an increase is the desired direction.
#
# For the current synthetic fitness fixtures:
#   - strength metrics: higher is better
#   - body-composition/general-fitness metrics: lower is better
HIGHER_IS_BETTER = {
    "bench_1rm_kg",
    "squat_1rm_kg",
}


def build_baseline_instruction(client: Client) -> str:
    """
    Build the instruction used to create the initial coaching plan.

    IMPORTANT:
    The assessment values are supplied explicitly to SuperDocs.

    The AI must:
        - use these values exactly
        - never calculate or estimate them
        - never replace them with placeholders
        - never write "Please fill:" when a supplied value exists
        - use "Not recorded" when a value genuinely does not exist
    """

    baseline = client.baseline()

    # ---------------------------------------------------------------
    # Build an explicit list of every baseline metric.
    # ---------------------------------------------------------------

    metric_lines: list[str] = []

    for key, label, unit in METRICS:
        value = baseline.get(key)

        if value is None:
            metric_lines.append(
                f"- {key}: {label}: Not recorded"
            )
        else:
            metric_lines.append(
                f"- {key}: {label}: {value} {unit}"
            )

    # ---------------------------------------------------------------
    # Optional programme fields.
    #
    # These attributes may not exist in every version of Client,
    # so getattr() prevents an AttributeError.
    # ---------------------------------------------------------------

    training_frequency = getattr(
        client,
        "training_frequency",
        None,
    )

    if not training_frequency:
        training_frequency = "Not recorded"

    daily_step_goal = getattr(
        client,
        "daily_step_goal",
        None,
    )

    if daily_step_goal is None:
        daily_step_goal = "Not recorded"

    # ---------------------------------------------------------------
    # Build the prompt.
    # ---------------------------------------------------------------

    return (
        "Create or update the client's INITIAL COACHING PLAN document.\n\n"

        "============================================================\n"
        "CRITICAL DATA RULES\n"
        "============================================================\n\n"

        "The data below is the authoritative source of truth.\n\n"

        "You MUST copy every supplied client value exactly.\n"
        "You MUST NOT calculate, estimate, round, infer, or invent "
        "measurement values.\n\n"

        "If a value is supplied below, it MUST appear in the document.\n"
        "If a value is marked 'Not recorded', display 'Not recorded'.\n\n"

        "IMPORTANT: The document may contain template text such as "
        "'Please fill: Weight', 'Please fill: Squat 1RM', "
        "'Please fill: Training frequency', or similar text.\n\n"

        "REMOVE AND REPLACE every 'Please fill:' placeholder.\n"
        "Do NOT leave any 'Please fill:' text in the final document.\n\n"

        "If the corresponding value is available below, replace the "
        "placeholder with that exact value.\n"
        "If the corresponding value is unavailable, replace the "
        "placeholder with 'Not recorded'.\n\n"

        "============================================================\n"
        "CLIENT INFORMATION\n"
        "============================================================\n\n"

        f"Client name: {client.display_name}\n"
        f"Client ID: {client.client_id}\n"
        f"Goal: {client.goal}\n"
        f"Status: {getattr(client, 'status', 'Active')}\n"
        f"Baseline assessment date: "
        f"{baseline.assessment_date.isoformat()}\n\n"

        "============================================================\n"
        "BASELINE MEASUREMENTS — SOURCE OF TRUTH\n"
        "============================================================\n\n"

        + "\n".join(metric_lines)

        + "\n\n"

        "============================================================\n"
        "PROGRAMME DETAILS — SOURCE OF TRUTH\n"
        "============================================================\n\n"

        f"- Training frequency: {training_frequency}\n"
        f"- Daily step goal: {daily_step_goal}\n\n"

        "============================================================\n"
        "REQUIRED DOCUMENT SECTIONS\n"
        "============================================================\n\n"

        "Create or update these sections:\n"
        "1. Client Overview\n"
        "2. Baseline Measurements\n"
        "3. Programme Overview\n"
        "4. Initial Plan Details\n"
        "5. Progress Report History\n\n"

        "============================================================\n"
        "BASELINE MEASUREMENTS INSTRUCTIONS\n"
        "============================================================\n\n"

        "The Baseline Measurements section MUST contain every metric "
        "listed above.\n\n"

        "Use these exact values:\n"
        + "\n".join(metric_lines)

        + "\n\n"

        "Do not substitute different numbers.\n"
        "Do not omit a metric because it is unfamiliar.\n"
        "Do not write 'Please fill'.\n\n"

        "============================================================\n"
        "PROGRAMME DETAILS INSTRUCTIONS\n"
        "============================================================\n\n"

        f"Training frequency must be: {training_frequency}\n"
        f"Daily step goal must be: {daily_step_goal}\n\n"

        "If either value is 'Not recorded', write exactly "
        "'Not recorded' rather than creating a placeholder.\n\n"

        "For nutrition and workout details that are not present in "
        "the supplied client data, do not invent client-specific "
        "measurements or claims. You may provide general coaching "
        "guidance appropriate to the client's stated goal, but clearly "
        "keep it generic rather than pretending it came from an "
        "assessment.\n\n"

        "============================================================\n"
        "FINAL QUALITY CHECK\n"
        "============================================================\n\n"

        "Before finishing the document, verify:\n"
        "1. Every baseline metric above appears in the document.\n"
        "2. Every available measurement uses the exact supplied value.\n"
        "3. No 'Please fill:' placeholders remain.\n"
        "4. Missing values say 'Not recorded'.\n"
        "5. Client ID and client name are correct.\n"
        "6. Baseline assessment date is correct.\n"
        "7. Training frequency and daily step goal use the supplied "
        "values or 'Not recorded'.\n\n"

        "Keep the document professional, clean, and client-friendly."
    )


def build_comparison_table_html(client: Client) -> str:
    """
    Build the deterministic baseline-vs-current comparison table.

    No network calls.
    No AI.
    All calculations are performed directly in Python.
    """

    baseline = client.baseline()
    current = client.latest()

    rows: list[str] = []

    for key, label, unit in METRICS:
        baseline_value = baseline.get(key)
        current_value = current.get(key)

        # Only compare metrics available at both points.
        if baseline_value is None or current_value is None:
            continue

        higher_is_better = key in HIGHER_IS_BETTER

        delta = _delta_str(
            baseline_value,
            current_value,
            higher_is_better,
        )

        rows.append(
            "<tr>"
            f"<td>{escape(label)}</td>"
            f"<td>{baseline_value} {escape(unit)}</td>"
            f"<td>{current_value} {escape(unit)}</td>"
            f"<td>{escape(delta)}</td>"
            "</tr>"
        )

    return (
        '<table data-report-section="comparison-table">'
        "<thead>"
        "<tr>"
        "<th>Metric</th>"
        f"<th>Baseline "
        f"({baseline.assessment_date.isoformat()})</th>"
        f"<th>Current "
        f"({current.assessment_date.isoformat()})</th>"
        "<th>Change</th>"
        "</tr>"
        "</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def build_adherence_line(client: Client) -> str:
    """Build deterministic adherence text."""

    current = client.latest()

    if current.adherence_pct is None:
        return (
            "<p><em>"
            "Adherence not recorded for this block."
            "</em></p>"
        )

    return (
        "<p>"
        "<strong>Adherence this block:</strong> "
        f"{current.adherence_pct:.0f}% "
        "of prescribed sessions completed."
        "</p>"
    )


def build_report_section_html(
    client: Client,
    chart_url: str,
) -> str:
    """
    Build the deterministic reassessment section.

    Contains:
        - comparison table
        - adherence
        - trend chart

    Numerical content is never generated by AI.
    """

    index = len(client.assessments) - 1

    date_str = client.latest().assessment_date.isoformat()

    return (
        f'<h2 data-report-block="{index}">'
        f"Progress Report — {escape(date_str)}"
        "</h2>"

        f"{build_comparison_table_html(client)}"

        f"{build_adherence_line(client)}"

        f'<img src="{escape(chart_url)}" '
        f'alt="Trend chart for '
        f'{escape(client.display_name)}" '
        f'data-report-section="trend-chart" />'
    )


def build_narrative_instruction(client: Client) -> str:
    """
    Build the AI-only narrative instruction.

    AI writes only:
        - What changed in the programme and why
        - Next block's goals

    AI does not calculate or modify measurement values.
    """

    index = len(client.assessments) - 1

    changes = client.program_changes_by_assessment.get(
        index,
        [],
    )

    goals = client.next_block_goals.get(
        index,
        [],
    )

    changes_text = (
        "; ".join(
            f"{change.change} "
            f"(reason: {change.reason})"
            for change in changes
        )
        or "no programme changes logged"
    )

    goals_text = (
        "; ".join(goals)
        or "no goals logged for the next block"
    )

    return (
        "Below the Progress Report table already present in "
        "the client's document, add exactly two short sections:\n\n"

        "1. What changed in the programme and why\n"
        "2. Next block's goals\n\n"

        "For 'What changed in the programme and why', use ONLY "
        "these logged facts:\n"
        f"{changes_text}\n\n"

        "For 'Next block's goals', use ONLY these logged goals:\n"
        f"{goals_text}\n\n"

        "Restate the supplied facts in natural, concise coaching "
        "language.\n\n"

        "Do not invent additional reasons, events, measurements, "
        "injuries, symptoms, achievements, or client preferences.\n\n"

        "Do not calculate or modify any number from the comparison "
        "table. The comparison table is already final and "
        "deterministically generated by Python.\n\n"

        "Do not change the baseline measurements.\n"
        "Do not add or modify 'Please fill:' placeholders.\n\n"

        "Keep both sections under 80 words combined.\n"
        "Match the tone of a personal trainer writing directly "
        "to the client."
    )