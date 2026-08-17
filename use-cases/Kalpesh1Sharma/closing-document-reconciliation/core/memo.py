from __future__ import annotations

from typing import Any


def _display_value(value: Any) -> str:
    if value is None:
        return "Not found"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"

        return f"{value:,.3f}".rstrip("0").rstrip(".")

    return str(value)


def _display_field_name(field_name: str) -> str:
    labels = {
        "loan_amount": "Loan Amount",
        "interest_rate": "Interest Rate",
        "term": "Loan Term",
        "escrow": "Escrow",
        "title_services": "Title & Settlement Services",
        "cash_to_close": "Cash to Close",
        "borrower_names": "Borrower Names",
        "property_address": "Property Address",
    }

    return labels.get(
        field_name,
        field_name.replace("_", " ").title(),
    )


def _observation_lines(
    finding: dict[str, Any],
) -> list[str]:
    lines = []

    for observation in finding.get(
        "observations",
        [],
    ):
        filename = observation.get(
            "filename",
            "Unknown document",
        )

        value = _display_value(
            observation.get("value")
        )

        raw_value = observation.get(
            "raw_value"
        )

        quote = observation.get(
            "supporting_quote"
        )

        line = f"- **{filename}:** {value}"

        if raw_value is not None:
            raw_text = str(raw_value)

            if raw_text != str(value):
                line += f" _(source value: {raw_text})_"

        lines.append(line)

        if quote:
            lines.append(
                f"  - Evidence: “{quote}”"
            )

    return lines


def render_reconciliation_memo(
    report: dict[str, Any],
) -> str:
    scenario_id = report.get(
        "scenario_id",
        "Unknown scenario",
    )

    findings = report.get(
        "findings",
        [],
    )

    curable = [
        finding
        for finding in findings
        if finding.get("classification")
        == "curable"
    ]

    tolerable = [
        finding
        for finding in findings
        if finding.get("classification")
        == "tolerable"
    ]

    matches = [
        finding
        for finding in findings
        if finding.get("status")
        == "match"
    ]

    unresolved = [
        finding
        for finding in findings
        if finding.get("classification")
        == "unclassified"
        or finding.get("status")
        in {
            "not_found",
            "insufficient_evidence",
        }
    ]

    lines = [
        "# Closing Document Reconciliation Memo",
        "",
        f"**Scenario:** {scenario_id}",
        "",
        (
            "This memo summarizes values extracted from the "
            "documents in the file and reconciles them using "
            "only the file-specific rules supplied in those "
            "documents."
        ),
        "",
        (
            "No external mortgage-law assumptions are used. "
            "Missing or unsupported information is not inferred."
        ),
        "",
        "## Executive Summary",
        "",
        f"- Matching fields: **{len(matches)}**",
        f"- Tolerable variances: **{len(tolerable)}**",
        f"- Curable variances: **{len(curable)}**",
        f"- Unresolved findings: **{len(unresolved)}**",
        "",
    ]

    if curable:
        lines.extend([
            (
                "**Funding review is required for the "
                "curable variance(s) identified below under "
                "the file's own rules.**"
            ),
            "",
        ])
    else:
        lines.extend([
            (
                "No curable variances were identified from "
                "the supported evidence."
            ),
            "",
        ])

    lines.extend([
        "## Detailed Reconciliation",
        "",
    ])

    for finding in findings:
        field_name = _display_field_name(
            finding.get(
                "field_name",
                "unknown",
            )
        )

        status = finding.get(
            "status",
            "unknown",
        ).replace("_", " ").title()

        classification = finding.get(
            "classification",
            "unknown",
        ).replace("_", " ").title()

        lines.extend([
            f"### {field_name}",
            "",
            f"**Status:** {status}",
            "",
            (
                f"**Classification:** "
                f"{classification}"
            ),
            "",
            "**Values by document:**",
            "",
        ])

        lines.extend(
            _observation_lines(
                finding
            )
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
                (
                    f"{rule.get('rule_text', '')}"
                ),
                "",
            ])

            supporting_quote = rule.get(
                "supporting_quote"
            )

            if supporting_quote:
                lines.extend([
                    (
                        "**Rule evidence:** "
                        f"“{supporting_quote}”"
                    ),
                    "",
                ])

        explanation = finding.get(
            "explanation"
        )

        if explanation:
            lines.extend([
                "**Reconciliation explanation:**",
                "",
                explanation,
                "",
            ])

        action = finding.get(
            "recommended_action"
        )

        if action:
            lines.extend([
                "**Recommended action:**",
                "",
                action,
                "",
            ])

        if finding.get(
            "requires_human_review"
        ):
            lines.extend([
                "**Human review required:** Yes",
                "",
            ])

        lines.extend([
            "---",
            "",
        ])

    lines.extend([
        "## Conclusion",
        "",
    ])

    if curable:
        lines.append(
            (
                f"{len(curable)} curable variance(s) require "
                "review or correction under the file-specific "
                "rules before the reconciliation can be "
                "treated as complete."
            )
        )
    else:
        lines.append(
            (
                "No curable variances were identified from "
                "the supported evidence."
            )
        )

    lines.extend([
        "",
        (
            "This memo is a synthetic demonstration and "
            "does not constitute legal, lending, compliance, "
            "or regulatory advice."
        ),
        "",
    ])

    return "\n".join(lines)