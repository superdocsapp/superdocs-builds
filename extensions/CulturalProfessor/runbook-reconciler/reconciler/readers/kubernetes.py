"""Kubernetes manifests: what is deployed, where, and how much of it.

Scope, stated rather than discovered later: **rendered manifests only.** Helm
charts and Kustomize overlays are not read. A chart's `values.yaml` says
`replicaCount: 3` and the manifest that eventually reaches the cluster may say
something else entirely once three overlays and a CI-time `--set` have had their
turn, so a reader that treats values files as ground truth reports a number
nobody deployed. That is worse than not reading them: it is a checker confidently
wrong, which is the exact failure this project exists to fix.

The honest version is to read what is committed as a manifest, and to say in the
README that estates templating everything need `helm template` output committed
or a rendered-manifests directory pointed at. That is a real limitation and it
is in the README under that name.

Multi-document files are handled — a `---` separated file of six resources is
normal, and reading only the first quietly loses five of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconciler.readers._source import SourceRef, iter_files, line_of, load_yaml_all

#: Only workloads. A ConfigMap or a Service is real infrastructure but nothing
#: in a runbook makes a checkable claim about one that this tool can settle, and
#: reading them would only inflate the "unverifiable" bucket with noise.
WORKLOAD_KINDS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job"})


@dataclass(frozen=True)
class Container:
    name: str
    image: str | None
    memory_limit: str | None
    cpu_limit: str | None
    readiness_path: str | None

    @property
    def image_tag(self) -> str | None:
        if not self.image or ":" not in self.image:
            return None
        return self.image.rsplit(":", 1)[1]


@dataclass(frozen=True)
class Workload:
    kind: str
    name: str
    namespace: str
    source: SourceRef
    replicas: int | None = None
    containers: tuple[Container, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()

    @property
    def ref(self) -> str:
        """`deploy/payments-api@payments` — the canonical subject for a workload.

        One spelling, used by every reader, rule and finding. Two spellings for
        the same entity is how a register ends up with a claim nobody can join
        to its ground truth.
        """
        return f"{self.kind.lower()}/{self.name}@{self.namespace}"


def read_workloads(paths: tuple[Path, ...]) -> list[Workload]:
    out: list[Workload] = []
    for path in iter_files(paths, "*.yaml", "*.yml"):
        out.extend(read_workloads_file(path))
    return out


def read_workloads_file(path: Path) -> list[Workload]:
    out: list[Workload] = []
    try:
        documents = load_yaml_all(path)
    except Exception:
        # A YAML file that does not parse is not necessarily broken -- Helm
        # templates are full of `{{ }}` and are not YAML until rendered. Skipping
        # is right; failing the whole sweep because somebody's chart is in the
        # same tree would make the tool unusable in the estates that need it.
        return out

    for document in documents:
        if not isinstance(document, dict):
            continue
        kind = str(document.get("kind", ""))
        if kind not in WORKLOAD_KINDS:
            continue
        metadata = document.get("metadata") or {}
        spec = document.get("spec") or {}
        pod_spec = _pod_spec(kind, spec)
        out.append(
            Workload(
                kind=kind,
                name=str(metadata.get("name", "")),
                # An unnamespaced manifest is applied into whatever namespace
                # the pipeline picked, which we cannot know. `default` is the
                # cluster's own answer and is at least not an invention.
                namespace=str(metadata.get("namespace") or "default"),
                source=SourceRef.of(path, metadata, line_of(document, 1)),
                replicas=_int_or_none(spec.get("replicas")),
                containers=tuple(_containers(pod_spec)),
                labels=tuple(
                    sorted((str(k), str(v)) for k, v in (metadata.get("labels") or {}).items())
                ),
            )
        )
    return out


def _pod_spec(kind: str, spec: dict[str, Any]) -> dict[str, Any]:
    """CronJob buries the pod two levels deeper than everything else."""
    if kind == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    template = spec.get("template") or {}
    return template.get("spec") or {}


def _containers(pod_spec: dict[str, Any]) -> list[Container]:
    out: list[Container] = []
    for container in pod_spec.get("containers") or []:
        limits = ((container.get("resources") or {}).get("limits")) or {}
        probe = (container.get("readinessProbe") or {}).get("httpGet") or {}
        out.append(
            Container(
                name=str(container.get("name", "")),
                image=_str_or_none(container.get("image")),
                memory_limit=_str_or_none(limits.get("memory")),
                cpu_limit=_str_or_none(limits.get("cpu")),
                readiness_path=_str_or_none(probe.get("path")),
            )
        )
    return out


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


__all__ = ["WORKLOAD_KINDS", "Container", "Workload", "read_workloads", "read_workloads_file"]
