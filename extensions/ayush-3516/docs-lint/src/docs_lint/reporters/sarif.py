"""SARIF 2.1.0 output, so GitHub renders findings inline on the pull request diff.

This is the format that makes the CI half of the card real: a reviewer sees the style problem
against the line that caused it, in the diff, without opening a log.
"""

from __future__ import annotations

import json

from ..model import RunSummary, Severity, Source
from ..rules import all_rules

SARIF_VERSION = "2.1.0"
SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"

#: SARIF has three levels and no "info" that renders usefully, so info maps to note.
LEVELS = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "note",
    Severity.OFF: "none",
}


def render_sarif(summary: RunSummary, *, error_on: frozenset[Severity]) -> str:
    return json.dumps(
        {
            "$schema": SCHEMA,
            "version": SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "docs-lint",
                            "informationUri": "https://github.com/superdocsapp/superdocs-builds",
                            "rules": _rule_descriptors(summary),
                        }
                    },
                    "invocations": [
                        {
                            # Reported honestly: a run that degraded says so here, so a green
                            # check on GitHub cannot quietly mean "we could not look".
                            "executionSuccessful": not summary.is_partial,
                            "toolExecutionNotifications": [
                                {"level": "warning", "message": {"text": note}}
                                for note in summary.degraded
                            ],
                        }
                    ],
                    "results": _results(summary),
                }
            ],
        },
        indent=2,
    )


def _rule_descriptors(summary: RunSummary) -> list[dict]:
    """Describe every rule that appears, including the two the model pass produces."""
    known = {rule.rule_id: rule.description for rule in all_rules()}
    known.setdefault("style-guide", "A correction proposed against the uploaded style guide.")
    known.setdefault(
        "unanchored-proposal",
        "A proposed change that did not correspond to any part of the document, and was discarded.",
    )

    seen = {f.rule_id for f in summary.all_findings}
    return [
        {
            "id": rule_id,
            "shortDescription": {"text": known.get(rule_id, rule_id)},
            "helpUri": "https://github.com/superdocsapp/superdocs-builds",
        }
        for rule_id in sorted(seen)
    ]


def _results(summary: RunSummary) -> list[dict]:
    results = []
    for file_result in summary.results:
        for finding in file_result.findings:
            entry = {
                "ruleId": finding.rule_id,
                "level": LEVELS.get(finding.severity, "note"),
                "message": {"text": _message(finding)},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.anchor.path},
                            "region": {
                                "startLine": finding.anchor.start_line,
                                "endLine": finding.anchor.end_line,
                            },
                        }
                    }
                ],
                "partialFingerprints": {"docsLintFindingId": finding.finding_id},
            }
            if finding.is_fixable and finding.original is not None:
                # SARIF fixes are advisory in GitHub's UI; nothing is applied from here. The
                # approval gate stays the only route by which a change reaches a file.
                entry["fixes"] = [
                    {
                        "description": {"text": f"Replace with {finding.replacement!r}"},
                        "artifactChanges": [
                            {
                                "artifactLocation": {"uri": finding.anchor.path},
                                "replacements": [
                                    {
                                        "deletedRegion": {
                                            "startLine": finding.anchor.start_line,
                                            "endLine": finding.anchor.end_line,
                                        },
                                        "insertedContent": {"text": finding.replacement or ""},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            results.append(entry)
    return results


def _message(finding) -> str:
    parts = [finding.message]
    if finding.source is Source.SUPERDOCS:
        parts.append("(proposed by the style-guide review)")
    if finding.explanation:
        parts.append(finding.explanation)
    return " ".join(parts)
