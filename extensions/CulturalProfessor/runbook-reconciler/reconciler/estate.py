"""Everything the readers found, plus the one hard question: what is this about?

The readers are pure and independent. This is where their output is joined, and
where the problem the brief calls risk 2 gets solved: a runbook says "the
payments service" or `tracking-api`, and ground truth says
`deployment/tracking-ingest@tracking`. Nothing checks out until those are known
to be the same thing.

Resolution runs in a fixed order, most trustworthy first, and each step is data
rather than code:

1. an exact workload name from a manifest;
2. a catalog component's current name;
3. a catalog component's `former-names` annotation — this is what turns a
   renamed service from "unverifiable" into "contradicts, and here is the new
   name";
4. `config/mappings.yaml`, the fallback for estates with no catalog.

`resolve()` returns *why* it matched as well as what it matched, because a
finding that says "renamed" needs to be able to show the annotation it believed.
An unattributed match is a guess wearing a suit.

Nothing here is fuzzy. There is no edit distance, no substring scoring, no
embedding. A near-match that is wrong produces a confident finding about the
wrong service, and the cost of that lands on somebody at three in the morning;
the cost of a miss is one `unverifiable` line in a report. Those are not the
same size of mistake and the code should not treat them as if they were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from reconciler.config import Config, Mappings
from reconciler.readers import alerts as alerts_reader
from reconciler.readers import catalog as catalog_reader
from reconciler.readers import ci as ci_reader
from reconciler.readers import dashboards as dashboards_reader
from reconciler.readers import escalation as escalation_reader
from reconciler.readers import terraform as terraform_reader
from reconciler.readers.alerts import AlertRule
from reconciler.readers.catalog import Component
from reconciler.readers.ci import Workflow
from reconciler.readers.dashboards import Dashboard
from reconciler.readers.escalation import Policy
from reconciler.readers.kubernetes import Workload, read_workloads
from reconciler.readers.terraform import Block


@dataclass(frozen=True)
class Resolution:
    """What a name in a document turned out to mean, and on what evidence."""

    name: str
    component: Component | None = None
    workload: Workload | None = None
    via: str = "none"

    @property
    def resolved(self) -> bool:
        return self.component is not None or self.workload is not None

    @property
    def renamed(self) -> bool:
        """The asked-for name is not the current one."""
        return self.via == "former-name" or (
            self.workload is not None and self.workload.name != self.name and self.resolved
        )

    @property
    def current_name(self) -> str | None:
        if self.workload:
            return self.workload.name
        if self.component:
            return self.component.name
        return None


@dataclass
class Estate:
    """Ground truth, read once, joined once."""

    alerts: list[AlertRule] = field(default_factory=list)
    workloads: list[Workload] = field(default_factory=list)
    workflows: list[Workflow] = field(default_factory=list)
    terraform: list[Block] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    policies: list[Policy] = field(default_factory=list)
    dashboards: list[Dashboard] = field(default_factory=list)
    mappings: Mappings = field(default_factory=Mappings)

    @classmethod
    def load(cls, config: Config | None = None) -> Estate:
        config = config or Config.load()
        paths: tuple[Path, ...] = config.infra_repo_paths
        return cls(
            alerts=alerts_reader.read_rules(paths),
            workloads=read_workloads(paths),
            workflows=ci_reader.read_workflows(paths),
            terraform=terraform_reader.read_terraform(paths),
            components=catalog_reader.read_catalog(paths),
            policies=escalation_reader.read_policies(paths),
            dashboards=dashboards_reader.read_dashboards(paths),
            mappings=config.mappings,
        )

    # ------------------------------------------------------------- lookups --

    def alert(self, name: str) -> AlertRule | None:
        return next((a for a in self.alerts if a.name == name), None)

    def workload(self, name: str, namespace: str | None = None) -> Workload | None:
        for workload in self.workloads:
            if workload.name == name and (namespace is None or workload.namespace == namespace):
                return workload
        return None

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)

    def dashboard(self, uid: str) -> Dashboard | None:
        return next((d for d in self.dashboards if d.uid == uid), None)

    def policy_named(self, spelling: str) -> Policy | None:
        """A rota by any name a document might plausibly use for it."""
        wanted = spelling.strip().lower()
        for policy in self.policies:
            if wanted in {s.lower() for s in policy.spellings}:
                return policy
        return None

    def policy_for_service(self, service: str) -> Policy | None:
        return next((p for p in self.policies if service in p.services), None)

    def workflow_for(self, repo: str) -> Workflow | None:
        return next((w for w in self.workflows if w.repo == repo), None)

    def job_named(self, name: str) -> tuple[Workflow, str] | None:
        for workflow in self.workflows:
            if workflow.job(name):
                return workflow, name
        return None

    # ---------------------------------------------------------- resolution --

    def resolve(self, name: str) -> Resolution:
        """What a name in a document refers to, and how we know.

        Exact matches only, in a fixed order of trustworthiness. See the module
        docstring for why there is no fuzzy fallback.
        """
        workload = self.workload(name)
        if workload:
            return Resolution(name, self.component(name), workload, via="workload")

        component = self.component(name)
        if component:
            return Resolution(name, component, self._workload_of(component), via="catalog")

        for candidate in self.components:
            if name in candidate.former_names:
                return Resolution(name, candidate, self._workload_of(candidate), via="former-name")

        mapped = self.mappings.aliases.get(name.lower()) or self.mappings.former_names.get(
            name.lower()
        )
        if mapped:
            component = self.component(mapped)
            resolved_workload = self.workload(mapped) or (
                self._workload_of(component) if component else None
            )
            if component or resolved_workload:
                return Resolution(name, component, resolved_workload, via="declared-mapping")

        return Resolution(name)

    def _workload_of(self, component: Component) -> Workload | None:
        if component.deployment:
            return self.workload(component.deployment, component.namespace)
        return self.workload(component.name)

    # ------------------------------------------------------------ coverage --

    def alerts_by_runbook_page(self) -> dict[str, list[AlertRule]]:
        out: dict[str, list[AlertRule]] = {}
        for alert in self.alerts:
            page = alert.runbook_page_id
            if page:
                out.setdefault(page, []).append(alert)
        return out

    def summary(self) -> dict[str, int]:
        return {
            "alerts": len(self.alerts),
            "workloads": len(self.workloads),
            "workflows": len(self.workflows),
            "terraform_blocks": len(self.terraform),
            "components": len(self.components),
            "escalation_policies": len(self.policies),
            "dashboards": len(self.dashboards),
        }


__all__ = ["Estate", "Resolution"]
