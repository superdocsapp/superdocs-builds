"""Escalation policies: who gets paged, and after how long.

Read from the declared configuration — the terraform module's inputs, an
Opsgenie or PagerDuty config file in the repo — and never from the provider's
API. That is a deliberate scope decision with a real cost and a real benefit.
The cost is that a rota renamed in the PagerDuty UI and never committed is
invisible here. The benefit is that the check is deterministic, offline, free,
and identical on every machine, and that the tool never needs a PagerDuty
credential to run.

A stale escalation target is one of the more expensive kinds of drift, which is
why it is in scope at all: a responder reading a rota name that no longer exists
spends the first five minutes of an incident searching for it.

The match is on both the policy `name` and its `display_name`, because runbooks
are written in prose and say "the Payments Core rota", not
`payments-core-oncall`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reconciler.readers._source import SourceRef, iter_files, load_yaml

_FILENAMES = ("escalation.yaml", "escalation.yml", "pagerduty.yaml", "opsgenie.yaml")


@dataclass(frozen=True)
class EscalationLevel:
    level: int
    target: str
    after_minutes: int | None


@dataclass(frozen=True)
class Policy:
    name: str
    source: SourceRef
    display_name: str | None = None
    services: tuple[str, ...] = ()
    levels: tuple[EscalationLevel, ...] = ()

    @property
    def spellings(self) -> tuple[str, ...]:
        """Every way a document might reasonably name this rota."""
        out = [self.name]
        if self.display_name:
            out.append(self.display_name)
            out.append(f"{self.display_name} rota")
        return tuple(out)

    def level_after(self, minutes: int) -> EscalationLevel | None:
        return next((lvl for lvl in self.levels if lvl.after_minutes == minutes), None)


def read_policies(paths: tuple[Path, ...]) -> list[Policy]:
    out: list[Policy] = []
    for path in iter_files(paths, *_FILENAMES):
        out.extend(read_policies_file(path))
    return out


def read_policies_file(path: Path) -> list[Policy]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        return []
    out: list[Policy] = []
    for policy in document.get("policies") or []:
        out.append(
            Policy(
                name=str(policy.get("name", "")),
                source=SourceRef.of(path, policy),
                display_name=(str(policy["display_name"]) if policy.get("display_name") else None),
                services=tuple(str(s) for s in policy.get("services") or ()),
                levels=tuple(
                    EscalationLevel(
                        level=int(level.get("level", 0)),
                        target=str(level.get("target", "")),
                        after_minutes=(
                            int(level["after_minutes"])
                            if level.get("after_minutes") is not None
                            else None
                        ),
                    )
                    for level in policy.get("escalation") or ()
                ),
            )
        )
    return out


__all__ = ["EscalationLevel", "Policy", "read_policies", "read_policies_file"]
