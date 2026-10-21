"""The rule interface and the registry.

A rule is a small object with an id, a default severity, and a `check`. It gets the parsed document
and its own options from the config, and returns findings. It does no I/O, costs nothing, and is
deterministic — which is precisely why these rules exist alongside the model pass rather than being
folded into it. A rule that should never vary should never be non-deterministic.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, ClassVar, Protocol, runtime_checkable

from ..config import Config
from ..model import Finding, Severity, Source
from ..parser import Document


@runtime_checkable
class Rule(Protocol):
    """What every local rule provides."""

    rule_id: ClassVar[str]
    default_severity: ClassVar[Severity]
    description: ClassVar[str]

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]: ...


class RuleBase:
    """Convenience base: gives rules a constructor-free identity and a finding factory."""

    rule_id: ClassVar[str] = ""
    default_severity: ClassVar[Severity] = Severity.WARNING
    description: ClassVar[str] = ""

    def finding(
        self,
        *,
        severity: Severity,
        message: str,
        anchor,
        replacement: str | None = None,
        original: str | None = None,
        explanation: str | None = None,
    ) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            severity=severity,
            message=message,
            anchor=anchor,
            source=Source.LOCAL,
            replacement=replacement,
            original=original,
            explanation=explanation,
        )

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        raise NotImplementedError


_REGISTRY: dict[str, RuleBase] = {}


def register(rule_class: type[RuleBase]) -> type[RuleBase]:
    """Class decorator: registers one instance of the rule and returns the class unchanged.

    Rules are stateless, so a single shared instance per rule is enough; per-run behaviour comes
    from the `options` passed to `check`, never from instance state.
    """
    instance = rule_class()
    if not instance.rule_id:
        raise ValueError(f"{rule_class.__name__} must define a rule_id")
    if instance.rule_id in _REGISTRY:
        raise ValueError(f"duplicate rule id {instance.rule_id!r}")
    _REGISTRY[instance.rule_id] = instance
    return rule_class


def all_rules() -> tuple[RuleBase, ...]:
    return tuple(_REGISTRY[rule_id] for rule_id in sorted(_REGISTRY))


def get_rule(rule_id: str) -> RuleBase | None:
    return _REGISTRY.get(rule_id)


def run_local_rules(document: Document, config: Config) -> Iterator[Finding]:
    """Run every enabled rule over a document, in a stable order.

    Severity comes from the config, not from the rule, so a team can demote a rule it disagrees
    with instead of forking the code. A rule set to `off` is never even constructed a finding for.
    """
    for rule in all_rules():
        severity = config.severity_for(rule.rule_id, rule.default_severity)
        if severity is Severity.OFF:
            continue
        options = config.options_for(rule.rule_id)
        for finding in rule.check(document, options):
            # The rule proposes a default severity; the config decides the real one.
            yield finding.model_copy(update={"severity": severity})
