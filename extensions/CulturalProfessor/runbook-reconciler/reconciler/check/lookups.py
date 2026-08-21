"""Answering "what does the estate actually say about this subject".

The boundary this module draws is the one that makes "configuration over code"
honest rather than a slogan. **A new rule is data** — `config/checks.yaml` binds
a subject pattern to a lookup and a comparison, and adding "check the escalation
policy's second level" is an entry there. **A new source of truth is code** —
teaching this tool that Datadog monitors exist means writing a reader and a
lookup, because no amount of YAML can invent knowledge of a file format.

Pretending otherwise would mean a rules file with Python in it, which is a
programming language with worse error messages.

Every lookup returns an `Observation` rather than a bare value, because "I could
not find out" is a first-class answer here and a `None` that means both "absent"
and "not applicable" is how a checker ends up reporting a claim as correct that
it never checked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from reconciler.estate import Estate
from reconciler.readers._source import SourceRef

#: `[5m]`, `[30m]`, `[1h]` — a PromQL range selector.
_RANGE = re.compile(r"\[(\d+[smhd])\]")


@dataclass(frozen=True)
class Observation:
    """What ground truth says, or an honest admission that it says nothing."""

    value: str | None = None
    source: SourceRef | None = None
    found: bool = False
    note: str = ""
    #: Free-form extras a comparison may need — the alerting expression, so a
    #: threshold in milliseconds can be compared with one in seconds.
    context: dict[str, Any] | None = None

    @classmethod
    def missing(cls, note: str, source: SourceRef | None = None) -> Observation:
        """Absence, with a citation where one exists.

        Rule 8 does not get a pass because the finding is about something that
        is not there. "No CI job called that" is only checkable in ten seconds
        if the reader is told *where this looked*, so closed-world lookups cite
        the scope they searched.
        """
        return cls(found=False, note=note, source=source)


Lookup = Callable[[Estate, dict[str, str], dict[str, Any]], Observation]
_REGISTRY: dict[str, Lookup] = {}


def lookup(name: str) -> Callable[[Lookup], Lookup]:
    def register(fn: Lookup) -> Lookup:
        _REGISTRY[name] = fn
        return fn

    return register


def get(name: str) -> Lookup | None:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)


# ----------------------------------------------------------------- alerts --


@lookup("alert_threshold")
def _alert_threshold(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    rule = estate.alert(groups.get("alert", ""))
    if not rule:
        return Observation.missing(f"no alerting rule named {groups.get('alert')!r}")
    if rule.threshold is None:
        # The reader declined to guess at this expression, so the checker
        # declines too. See readers/alerts.py.
        return Observation.missing(
            f"the expression for {rule.name} has no trailing numeric comparison, "
            f"so its threshold cannot be read without interpreting PromQL"
        )
    return Observation(
        value=_trim(rule.threshold),
        source=rule.source,
        found=True,
        context={"expr": rule.expr, "operator": rule.operator},
    )


@lookup("alert_for")
def _alert_for(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    rule = estate.alert(groups.get("alert", ""))
    if not rule or rule.duration_seconds is None:
        return Observation.missing(f"no `for` clause on {groups.get('alert')!r}")
    return Observation(
        value=rule.duration,
        source=rule.source,
        found=True,
        context={"seconds": rule.duration_seconds},
    )


@lookup("alert_window")
def _alert_window(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    """The query's range selector, which is not the same thing as `for`.

    A runbook saying "5% over a 30 minute window" is describing `[30m]` in the
    expression. Conflating the two produces a confident finding about the wrong
    number, which is worse than not checking it.
    """
    rule = estate.alert(groups.get("alert", ""))
    if not rule:
        return Observation.missing(f"no alerting rule named {groups.get('alert')!r}")
    ranges = _RANGE.findall(rule.expr)
    if not ranges:
        return Observation.missing(f"{rule.name} has no range selector to compare against")
    return Observation(
        value=", ".join(sorted(set(ranges))),
        source=rule.source,
        found=True,
        context={"ranges": ranges},
    )


@lookup("alert_exists")
def _alert_exists(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    rule = estate.alert(groups.get("alert", ""))
    if not rule:
        return Observation.missing(f"no alerting rule named {groups.get('alert')!r}")
    return Observation(value=rule.name, source=rule.source, found=True)


# ------------------------------------------------------------- workloads --


@lookup("workload_name")
def _workload_name(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    name = groups.get("name", "")
    resolution = estate.resolve(name)
    if not resolution.resolved:
        return Observation.missing(f"nothing in the declared estate is named {name!r}")
    current = resolution.current_name or name
    source = resolution.workload.source if resolution.workload else resolution.component.source
    return Observation(
        value=current,
        source=source,
        found=True,
        note=f"resolved via {resolution.via}",
        context={"renamed": resolution.renamed, "via": resolution.via},
    )


@lookup("workload_namespace")
def _workload_namespace(
    estate: Estate, groups: dict[str, str], args: dict[str, Any]
) -> Observation:
    resolution = estate.resolve(groups.get("name", ""))
    if not resolution.workload:
        return Observation.missing(f"no manifest found for {groups.get('name')!r}")
    return Observation(
        value=resolution.workload.namespace, source=resolution.workload.source, found=True
    )


@lookup("workload_replicas")
def _workload_replicas(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    resolution = estate.resolve(groups.get("name", ""))
    if not resolution.workload or resolution.workload.replicas is None:
        return Observation.missing(f"no replica count declared for {groups.get('name')!r}")
    return Observation(
        value=str(resolution.workload.replicas), source=resolution.workload.source, found=True
    )


@lookup("namespace_exists")
def _namespace_exists(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    wanted = groups.get("namespace", "")
    for workload in estate.workloads:
        if workload.namespace == wanted:
            return Observation(value=wanted, source=workload.source, found=True)
    return Observation.missing(f"no workload is declared in namespace {wanted!r}")


# ------------------------------------------------------------------- ci ----


@lookup("ci_job")
def _ci_job(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    name = groups.get("job", "")
    found = estate.job_named(name)
    if found:
        workflow, _ = found
        job = workflow.job(name)
        return Observation(value=name, source=job.source, found=True)
    # Naming the jobs that do exist is what turns "that job is gone" into a
    # finding somebody can act on in one read.
    candidates = sorted({job.name for w in estate.workflows for job in w.jobs})
    return Observation.missing(
        f"no CI job named {name!r}; the declared jobs are {', '.join(candidates)}",
        source=_scope([w.source for w in estate.workflows]),
    )


# ----------------------------------------------------------- escalation ----


@lookup("escalation_policy")
def _escalation_policy(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    spelling = groups.get("rota", "")
    policy = estate.policy_named(spelling) or estate.policy_named(f"{spelling} rota")
    if policy:
        return Observation(
            value=policy.display_name or policy.name, source=policy.source, found=True
        )
    known = sorted({p.display_name or p.name for p in estate.policies})
    return Observation.missing(
        f"no escalation policy answers to {spelling!r}; the declared rotas are {', '.join(known)}",
        source=_scope([p.source for p in estate.policies]),
    )


# ------------------------------------------------------------ dashboards ---


@lookup("dashboard")
def _dashboard(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    uid = groups.get("uid", "")
    dashboard = estate.dashboard(uid)
    if dashboard:
        return Observation(value=dashboard.uid, source=dashboard.source, found=True)
    return Observation.missing(
        f"no dashboard with uid {uid!r} is declared in the repository. This tool reads "
        f"dashboards from git, not from Grafana, so a dashboard that exists only in the "
        f"Grafana database will look like this too",
        source=_scope([d.source for d in estate.dashboards]),
    )


# ------------------------------------------------------------- terraform ---


@lookup("terraform_attribute")
def _terraform_attribute(
    estate: Estate, groups: dict[str, str], args: dict[str, Any]
) -> Observation:
    from reconciler.readers.terraform import find_resource

    resource = find_resource(estate.terraform, args.get("type", ""), args.get("name", ""))
    if not resource:
        return Observation.missing(
            f"no terraform resource {args.get('type')}.{args.get('name')} in the declared config"
        )
    attribute = str(args.get("attribute", ""))
    found = resource.find_attribute(attribute)
    if not found:
        return Observation.missing(f"{resource.address} declares no {attribute}")
    value, owner = found
    if attribute in owner.unresolved:
        return Observation.missing(
            f"{resource.address}.{attribute} is {value!r}, a reference this tool does not "
            f"evaluate. Resolving it properly means implementing Terraform"
        )
    return Observation(value=value, source=resource.source, found=True)


@lookup("cloud_region")
def _cloud_region(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    for block in estate.terraform:
        if block.type == "provider" and block.get("region"):
            return Observation(value=block.get("region"), source=block.source, found=True)
    return Observation.missing("no provider block declares a region")


@lookup("entity_exists")
def _entity_exists(estate: Estate, groups: dict[str, str], args: dict[str, Any]) -> Observation:
    """Does this identifier name anything at all in the declared estate?

    Deliberately broad and deliberately weak: it answers yes across workloads,
    CI jobs, terraform literals and catalog entries, and a "no" is reported
    `unverifiable` rather than `contradicts`. A hyphenated token in a code span
    might be a resource name, a placeholder or an example, and this tool cannot
    tell the difference. Confirming the ones it can find is worth something;
    accusing the rest is not.
    """
    name = groups.get("name", "")
    workload = estate.workload(name)
    if workload:
        return Observation(value=name, source=workload.source, found=True, note="a workload")
    job = estate.job_named(name)
    if job:
        workflow, _ = job
        return Observation(
            value=name, source=workflow.job(name).source, found=True, note="a CI job"
        )
    literal = estate.terraform_literals.get(name)
    if literal:
        block, attribute = literal
        return Observation(
            value=name,
            source=block.source,
            found=True,
            note=f"{block.address}.{attribute}",
        )
    component = estate.component(name)
    if component:
        return Observation(value=name, source=component.source, found=True, note="a catalog entry")
    return Observation.missing(f"{name!r} does not appear in any declared configuration")


def _scope(sources: list[SourceRef]) -> SourceRef | None:
    """The narrowest place that contains everything a closed-world lookup read.

    One file when only one was read, otherwise the directory they share. It is
    what makes an absence checkable: "not in any of these" is a claim a reader
    can go and test, and "not found" on its own is not.
    """
    if not sources:
        return None
    if len(sources) == 1:
        return sources[0]
    parts = [source.file.split("/") for source in sources]
    shared: list[str] = []
    for segments in zip(*parts, strict=False):
        if len(set(segments)) != 1:
            break
        shared.append(segments[0])
    return SourceRef("/".join(shared) or ".", 1)


def _trim(value: float) -> str:
    """`1.2` rather than `1.2000000000000002`, and `3` rather than `3.0`."""
    return f"{value:g}"


__all__ = ["Lookup", "Observation", "get", "lookup", "names"]
