"""Load the tiny live-demo subset and build a compact framework payload."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from job_architecture.architecture import ArchitectureResult, build_architecture
from job_architecture.fixtures import FIXTURES_ROOT, load_corpus
from job_architecture.framework import FrameworkDocument, generate_framework
from job_architecture.models import RoleProfile

SUBSET_PATH = FIXTURES_ROOT / "live" / "demo-subset.json"


@dataclass(frozen=True)
class DemoRole:
    role_id: str
    kind: str
    purpose: str


@dataclass(frozen=True)
class DemoSubset:
    corpus_id: str
    session_id: str
    search_query: str
    surgical_role_id: str | None
    roles: tuple[DemoRole, ...]

    @property
    def role_ids(self) -> tuple[str, ...]:
        return tuple(item.role_id for item in self.roles)


def load_demo_subset(path: Path | None = None) -> DemoSubset:
    payload = json.loads((path or SUBSET_PATH).read_text(encoding="utf-8"))
    roles = tuple(
        DemoRole(
            role_id=item["role_id"],
            kind=item["kind"],
            purpose=item.get("purpose") or "",
        )
        for item in payload["roles"]
    )
    return DemoSubset(
        corpus_id=payload["corpus_id"],
        session_id=payload.get("session_id") or "job-arch-live",
        search_query=payload.get("search_query")
        or "Find documents or role profiles that reference the IC4 level.",
        surgical_role_id=payload.get("surgical_role_id"),
        roles=roles,
    )


def build_demo_framework(subset: DemoSubset | None = None) -> tuple[ArchitectureResult, FrameworkDocument]:
    spec = subset or load_demo_subset()
    corpus = load_corpus(spec.corpus_id)
    architecture = build_architecture(corpus)
    # Full-corpus architecture keeps clustering honest; live documents only
    # serialize the subset roles.
    full = generate_framework(architecture, tuple(_evidences(corpus)))
    return architecture, full


def _evidences(corpus):
    from job_architecture.architecture import extract_corpus_evidence

    return extract_corpus_evidence(corpus)


def subset_profiles(framework: FrameworkDocument, subset: DemoSubset) -> tuple[RoleProfile, ...]:
    wanted = set(subset.role_ids)
    return tuple(item for item in framework.profiles if item.role_id in wanted)


def surgical_target_profile(framework: FrameworkDocument, subset: DemoSubset) -> RoleProfile:
    """Prefer the fixture's occupied IC profile; otherwise IC4, else the highest IC."""
    subset_ids = set(subset.role_ids)
    if subset.surgical_role_id:
        named = [
            item
            for item in framework.profiles
            if item.role_id == subset.surgical_role_id
        ]
        if named:
            return named[0]
    ic4 = [
        item
        for item in framework.profiles
        if item.role_id in subset_ids and item.level_label == "IC4"
    ]
    if ic4:
        return ic4[0]
    ranked = [
        item
        for item in framework.profiles
        if item.role_id in subset_ids and item.level_label.startswith("IC")
    ]
    if not ranked:
        raise ValueError("Demo subset has no classified IC profile for the surgical update")
    ranked.sort(key=lambda item: item.level_label, reverse=True)
    return ranked[0]
