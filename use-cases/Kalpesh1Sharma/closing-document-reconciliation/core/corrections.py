from __future__ import annotations

from typing import Any


def _display_field_name(
    field_name: str,
) -> str:
    labels = {
        "loan_amount": "Loan Amount",
        "interest_rate": "Interest Rate",
        "term": "Loan Term",
        "escrow": "Escrow",
        "title_services": (
            "Title & Settlement Services"
        ),
        "cash_to_close": "Cash to Close",
        "borrower_names": "Borrower Names",
        "property_address": "Property Address",
    }

    return labels.get(
        field_name,
        field_name.replace(
            "_",
            " ",
        ).title(),
    )


def _format_value(value: Any) -> str:
    if value is None:
        return "Not found"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"

        return (
            f"{value:,.3f}"
            .rstrip("0")
            .rstrip(".")
        )

    return str(value)


def render_correction_request(
    report: dict[str, Any],
) -> str:
    """
    Produce a correction/revised-disclosure request using
    ONLY findings already classified as CURABLE.

    No new facts or rules are introduced here.
    """

    scenario_id = report.get(
        "scenario_id",
        "Unknown scenario",
    )

    findings = report.get(
        "findings",
        [],
    )

    curable_findings = [
        finding
        for finding in findings
        if finding.get(
            "classification"
        ) == "curable"
    ]

    lines = [
        "# Revised Disclosure / Correction Request",
        "",
        f"**Scenario:** {scenario_id}",
        "",
        (
            "The following items were identified as "
            "curable variances during document "
            "reconciliation."
        ),
        "",
        (
            "This request is based only on values and "
            "file-specific rules supported by the "
            "provided documents."
        ),
        "",
    ]

    if not curable_findings:
        lines.extend([
            (
                "No curable variance was identified. "
                "No correction request is required."
            ),
            "",
        ])

        return "\n".join(lines)

    lines.extend([
        "## Requested Corrections",
        "",
    ])

    for number, finding in enumerate(
        curable_findings,
        start=1,
    ):
        name = _display_field_name(
            finding.get(
                "field_name",
                "unknown",
            )
        )

        lines.extend([
            f"### {number}. {name}",
            "",
            "**Observed values:**",
            "",
        ])

        for observation in finding.get(
            "observations",
            [],
        ):
            value = _format_value(
                observation.get("value")
            )

            filename = observation.get(
                "filename",
                "Unknown document",
            )

            lines.append(
                f"- **{filename}:** {value}"
            )

            quote = observation.get(
                "supporting_quote"
            )

            if quote:
                lines.append(
                    f"  - Evidence: “{quote}”"
                )

        lines.append("")

        rule = finding.get(
            "applicable_rule"
        )

        if rule:
            lines.extend([
                (
                    f"**Applicable file rule:** "
                    f"{rule.get('rule_id', 'Unknown')}"
                ),
                "",
                rule.get(
                    "rule_text",
                    "",
                ),
                "",
            ])

        explanation = finding.get(
            "explanation"
        )

        if explanation:
            lines.extend([
                "**Reason for request:**",
                "",
                explanation,
                "",
            ])

        action = finding.get(
            "recommended_action"
        )

        if action:
            lines.extend([
                "**Requested action:**",
                "",
                action,
                "",
            ])

        lines.extend([
            "---",
            "",
        ])

    lines.extend([
        "## Review Status",
        "",
        (
            "These items remain subject to human review. "
            "The generated request does not represent "
            "automatic approval, funding authorization, "
            "or a legal determination."
        ),
        "",
    ])

    return "\n".join(lines)