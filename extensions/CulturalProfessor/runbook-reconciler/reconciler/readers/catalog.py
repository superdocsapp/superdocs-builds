"""Backstage `catalog-info.yaml`: ownership, tier, and — the useful part —
entity resolution.

This reader settles a few claims directly (who owns a service, what tier it is)
but its real job is the one from risk 2 of the brief: mapping "the payments
service", written in prose in 2023, onto `deploy/payments-api` in namespace
`payments` as it exists today.

The annotation that does the most work is `meridian.io/former-names`. Without
it, a runbook naming `tracking-api` looks like a runbook about a service that
never existed, and the only honest verdict is `unverifiable`. With it, the same
page produces `contradicts` with a proposed rename — a finding somebody can act
on. The difference between those two outcomes is one annotation, which is worth
saying out loud in the README: **this tool is much better in an estate that
keeps a catalog**, and the `config/mappings.yaml` fallback is a fallback, not a
substitute.

Annotation keys are read from a list rather than hardcoded one per line, because
every organisation prefixes them differently and changing that should not be a
code change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reconciler.readers._source import SourceRef, iter_files, load_yaml

#: Candidate annotation keys, most specific first. Estates use their own
#: prefixes; adding one is a list entry.
DEPLOYMENT_KEYS = ("meridian.io/kubernetes-deployment", "backstage.io/kubernetes-id")
NAMESPACE_KEYS = ("meridian.io/kubernetes-namespace", "backstage.io/kubernetes-namespace")
FORMER_NAME_KEYS = ("meridian.io/former-names", "backstage.io/former-names")
ESCALATION_KEYS = ("pagerduty.com/escalation-policy", "opsgenie.com/team")
DASHBOARD_KEYS = ("grafana/dashboard-uid", "grafana.com/dashboard-uid")


@dataclass(frozen=True)
class Component:
    name: str
    source: SourceRef
    owner: str | None = None
    tier: str | None = None
    lifecycle: str | None = None
    description: str = ""
    deployment: str | None = None
    namespace: str | None = None
    escalation_policy: str | None = None
    dashboard_uid: str | None = None
    former_names: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Every name this component has answered to."""
        return (self.name, *self.former_names)

    @property
    def workload_ref(self) -> str | None:
        if not (self.deployment and self.namespace):
            return None
        return f"deployment/{self.deployment}@{self.namespace}"


def read_catalog(paths: tuple[Path, ...]) -> list[Component]:
    out: list[Component] = []
    for path in iter_files(paths, "catalog-info.yaml", "catalog-info.yml"):
        component = read_catalog_file(path)
        if component:
            out.append(component)
    return out


def read_catalog_file(path: Path) -> Component | None:
    document = load_yaml(path)
    if not isinstance(document, dict) or document.get("kind") != "Component":
        return None
    metadata = document.get("metadata") or {}
    spec = document.get("spec") or {}
    annotations = metadata.get("annotations") or {}
    return Component(
        name=str(metadata.get("name", "")),
        source=SourceRef.of(path, metadata),
        owner=_str_or_none(spec.get("owner")),
        tier=_str_or_none(spec.get("tier")),
        lifecycle=_str_or_none(spec.get("lifecycle")),
        description=str(metadata.get("description", "")),
        deployment=_first(annotations, DEPLOYMENT_KEYS),
        namespace=_first(annotations, NAMESPACE_KEYS),
        escalation_policy=_first(annotations, ESCALATION_KEYS),
        dashboard_uid=_first(annotations, DASHBOARD_KEYS),
        former_names=_csv(_first(annotations, FORMER_NAME_KEYS)),
    )


def _first(annotations: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if annotations.get(key) is not None:
            return str(annotations[key])
    return None


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = ["Component", "read_catalog", "read_catalog_file"]
