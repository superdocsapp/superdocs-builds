"""JSON output: the machine's view of a run.

Includes what did *not* happen — skipped files, degraded stages, the checks that ran per file — so
a program consuming this can tell a clean repository from an unchecked one. A format that only
listed findings would make those two look identical.
"""

from __future__ import annotations

import json

from ..model import RunSummary, Severity


def render_json(summary: RunSummary, *, error_on: frozenset[Severity]) -> str:
    payload = {
        "run_id": summary.run_id,
        "headline": summary.headline(error_on),
        "exit_code": summary.exit_code(error_on),
        "partial": summary.is_partial,
        "counts": summary.counts(),
        "operations_charged": summary.ops_charged,
        "stage_seconds": {k: round(v, 3) for k, v in sorted(summary.stage_seconds.items())},
        "degraded": list(summary.degraded),
        "files": [
            {
                "path": result.path,
                "verdict": result.verdict.kind.value,
                "reason": result.verdict.reason,
                "checks_run": list(result.verdict.checks_run),
                "from_cache": result.from_cache,
                "seconds": round(result.seconds, 3),
                "operations_charged": result.ops_charged,
                "findings": [
                    {
                        "id": finding.finding_id,
                        "rule": finding.rule_id,
                        "severity": finding.severity.value,
                        "source": finding.source.value,
                        "message": finding.message,
                        "explanation": finding.explanation,
                        "location": {
                            "path": finding.anchor.path,
                            "section": finding.anchor.section,
                            "start_line": finding.anchor.start_line,
                            "end_line": finding.anchor.end_line,
                            "start_char": finding.anchor.start_char,
                            "end_char": finding.anchor.end_char,
                        },
                        "original": finding.original,
                        "replacement": finding.replacement,
                        "fixable": finding.is_fixable,
                    }
                    for finding in result.findings
                ],
            }
            for result in summary.results
        ],
    }
    return json.dumps(payload, indent=2)
