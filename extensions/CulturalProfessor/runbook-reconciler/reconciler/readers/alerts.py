"""Prometheus alerting rules: thresholds, severities, and `runbook_url`.

The one interesting problem here is pulling a threshold out of a PromQL
expression without implementing PromQL. The approach is deliberately narrow: the
*trailing* comparison of the expression is the alerting condition, so

    histogram_quantile(0.99, sum(rate(...[5m])) by (le)) > 1.2

yields `> 1.2` and nothing else is interpreted. The `0.99` inside the quantile
and the `5m` inside the rate are not thresholds and this reader never confuses
them for one, because it only ever looks at the end of the string.

What that costs is honest and stated rather than hidden: an expression whose
alerting condition is not a trailing numeric comparison — `absent()`,
`... > on(job) group_left ...`, a comparison in the middle of an arithmetic
expression — yields no threshold at all. Those come back as `threshold=None`,
and a claim about them is `unverifiable`. Guessing would be worse: a wrong
threshold reported confidently is exactly the failure this project exists to
fix, and doing it ourselves would be embarrassing.

Units are the second trap. Prometheus histograms are in seconds and runbooks are
written in milliseconds, so `> 1.2` and "800ms" are not comparable as numbers.
`comparable_values()` handles the conversion in one place, and the check rules
say which unit family a subject belongs to rather than each rule guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from reconciler.readers._source import SourceRef, iter_files, line_of, load_yaml

#: The alerting condition, anchored to the end of the expression. Anchoring is
#: the whole point -- an unanchored search finds the `0.99` in a quantile.
_TRAILING_COMPARISON = re.compile(r"([<>]=?|==|!=)\s*(-?\d+(?:\.\d+)?)\s*$")

#: `/pages/1001` and `/pages/1001/Runbook+title` both mean page 1001.
_PAGE_ID = re.compile(r"/pages/(\d+)")

_DURATION = re.compile(r"^(\d+)([smhd])$")
_SECONDS_PER = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class AlertRule:
    name: str
    expr: str
    group: str
    source: SourceRef
    duration: str | None = None
    severity: str | None = None
    team: str | None = None
    runbook_url: str | None = None
    summary: str | None = None
    threshold: float | None = None
    operator: str | None = None

    @property
    def runbook_page_id(self) -> str | None:
        if not self.runbook_url:
            return None
        match = _PAGE_ID.search(self.runbook_url)
        return match.group(1) if match else None

    @property
    def duration_seconds(self) -> int | None:
        return duration_seconds(self.duration) if self.duration else None


def duration_seconds(text: str) -> int | None:
    """`10m` -> 600. Returns None rather than guessing at anything else."""
    match = _DURATION.match(text.strip())
    if not match:
        return None
    return int(match.group(1)) * _SECONDS_PER[match.group(2)]


def parse_threshold(expr: str) -> tuple[str, float] | None:
    """The trailing comparison of a PromQL expression, or nothing.

    Returning nothing is a real answer here, not a failure. See the module
    docstring: an expression this cannot read produces an unverifiable claim,
    which is the honest outcome.
    """
    match = _TRAILING_COMPARISON.search(expr.strip())
    if not match:
        return None
    return match.group(1), float(match.group(2))


def read_rules(paths: tuple[Path, ...], pattern: str = "*.rules.yml") -> list[AlertRule]:
    rules: list[AlertRule] = []
    for path in iter_files(paths, pattern, "*.rules.yaml"):
        rules.extend(read_rules_file(path))
    return rules


def read_rules_file(path: Path) -> list[AlertRule]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        return []
    out: list[AlertRule] = []
    for group in document.get("groups") or []:
        group_name = str(group.get("name", ""))
        for rule in group.get("rules") or []:
            name = rule.get("alert")
            if not name:  # a recording rule: not an alert, not our business
                continue
            labels = rule.get("labels") or {}
            annotations = rule.get("annotations") or {}
            expr = str(rule.get("expr", ""))
            comparison = parse_threshold(expr)
            out.append(
                AlertRule(
                    name=str(name),
                    expr=expr,
                    group=group_name,
                    source=SourceRef.of(path, rule, line_of(group, 1)),
                    duration=str(rule["for"]) if rule.get("for") else None,
                    severity=_str_or_none(labels.get("severity")),
                    team=_str_or_none(labels.get("team")),
                    runbook_url=_str_or_none(annotations.get("runbook_url")),
                    summary=_str_or_none(annotations.get("summary")),
                    operator=comparison[0] if comparison else None,
                    threshold=comparison[1] if comparison else None,
                )
            )
    return out


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = ["AlertRule", "duration_seconds", "parse_threshold", "read_rules", "read_rules_file"]
