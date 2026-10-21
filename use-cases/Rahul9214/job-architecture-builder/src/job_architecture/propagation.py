"""Impact analysis and surgical profile updates. Plan, review, then apply."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Mapping, Sequence

from job_architecture.graph import (
    SECTION_LEVEL_EXPECTATIONS,
    SOURCE_LEVEL,
    DependencyGraph,
    DependencyGraphError,
    bump_level_edge_versions,
    validate_dependency_graph,
)
from job_architecture.hashes import hash_all_sections, hash_payload, hash_section
from job_architecture.level_text import (
    RENDERED_FIELDS,
    changed_dimensions,
    field_preservation_violations,
    patch_level_expectations,
    rendered_fields_for,
)
from job_architecture.models import (
    PROFILE_SECTION_IDS,
    DependencyEdge,
    LevelDefinition,
    RoleProfile,
)
from job_architecture.profile_structure import validate_level_expectations_block


class ChangeStatus(StrEnum):
    PLANNED = "planned"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


@dataclass(frozen=True)
class ImpactedSection:
    profile_id: str
    section_id: str
    reason: str
    old_dependency_version: int
    new_dependency_version: int
    edge_id: str


@dataclass(frozen=True)
class ImpactAnalysis:
    level_id: str
    affected_profile_ids: tuple[str, ...]
    unaffected_profile_ids: tuple[str, ...]
    affected_sections: tuple[ImpactedSection, ...]
    reason: str
    old_dependency_version: int
    new_dependency_version: int
    changed_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdatePlan:
    profile_id: str
    section_id: str
    before: str
    after: str
    reason: str
    dependency: DependencyEdge
    old_hash: str
    new_hash: str
    status: ChangeStatus = ChangeStatus.PLANNED
    changed_dimensions: tuple[str, ...] = ()
    changed_rendered_fields: tuple[str, ...] = ()
    preserved_rendered_fields: tuple[str, ...] = ()

    def with_status(self, status: ChangeStatus) -> UpdatePlan:
        return replace(self, status=status)


@dataclass(frozen=True)
class SectionHash:
    profile_id: str
    section_id: str
    digest: str


@dataclass(frozen=True)
class PreservationReport:
    changed_sections: tuple[SectionHash, ...]
    unchanged_sections: tuple[SectionHash, ...]
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def _as_text(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def analyze_level_change(
    old_level_definition: LevelDefinition,
    new_level_definition: LevelDefinition,
    dependency_graph: DependencyGraph,
    profiles: Sequence[RoleProfile],
    *,
    levels: Sequence[LevelDefinition],
) -> ImpactAnalysis:
    if old_level_definition.id != new_level_definition.id:
        raise DependencyGraphError(
            "Impact analysis requires the same level id on old and new definitions"
        )
    validate_dependency_graph(dependency_graph, profiles, levels)
    changed = tuple(sorted(changed_dimensions(old_level_definition, new_level_definition)))
    edges = dependency_graph.for_source(SOURCE_LEVEL, old_level_definition.id)
    profile_ids = {item.id for item in profiles}
    affected_sections: list[ImpactedSection] = []
    affected: set[str] = set()
    for edge in edges:
        if edge.target_id not in profile_ids:
            raise DependencyGraphError(f"Dangling profile target {edge.target_id}")
        affected.add(edge.target_id)
        affected_sections.append(
            ImpactedSection(
                profile_id=edge.target_id,
                section_id=edge.target_section,
                reason=(
                    f"Profile section {edge.target_section} depends on "
                    f"{old_level_definition.label} version {edge.source_version}"
                ),
                old_dependency_version=edge.source_version,
                new_dependency_version=new_level_definition.version,
                edge_id=edge.id,
            )
        )
    unaffected = tuple(sorted(profile_ids - affected))
    return ImpactAnalysis(
        level_id=old_level_definition.id,
        affected_profile_ids=tuple(sorted(affected)),
        unaffected_profile_ids=unaffected,
        affected_sections=tuple(affected_sections),
        reason=(
            f"Canonical {old_level_definition.label} changed from version "
            f"{old_level_definition.version} to {new_level_definition.version}"
            + (f"; dimensions: {', '.join(changed)}" if changed else "")
        ),
        old_dependency_version=old_level_definition.version,
        new_dependency_version=new_level_definition.version,
        changed_dimensions=changed,
    )


def plan_level_updates(
    analysis: ImpactAnalysis,
    *,
    old_level: LevelDefinition,
    new_level: LevelDefinition,
    dependency_graph: DependencyGraph,
    profiles: Sequence[RoleProfile],
) -> tuple[UpdatePlan, ...]:
    by_id = {item.id: item for item in profiles}
    canonical = changed_dimensions(old_level, new_level)
    changed_fields = tuple(sorted(rendered_fields_for(canonical)))
    preserved_fields = tuple(item for item in RENDERED_FIELDS if item not in set(changed_fields))
    plans: list[UpdatePlan] = []
    for item in analysis.affected_sections:
        if item.section_id != SECTION_LEVEL_EXPECTATIONS:
            continue
        profile = by_id[item.profile_id]
        before = _as_text(profile.section_value(item.section_id))
        structure = validate_level_expectations_block(before)
        if not structure.ok:
            raise DependencyGraphError(
                f"Refusing to plan a surgical update against malformed level_expectations "
                f"on {profile.id}: " + "; ".join(structure.violations)
            )
        after = patch_level_expectations(before, new_level, canonical)
        if before == after:
            continue
        field_violations = field_preservation_violations(before, after, changed_fields)
        if field_violations:
            raise DependencyGraphError(
                "Dimension-surgical planning rewrote unchanged fields: "
                + "; ".join(field_violations)
            )
        edge = next(edge for edge in dependency_graph.edges if edge.id == item.edge_id)
        plans.append(
            UpdatePlan(
                profile_id=profile.id,
                section_id=item.section_id,
                before=before,
                after=after,
                reason=item.reason,
                dependency=edge,
                old_hash=hash_section(profile, item.section_id),
                new_hash=hash_payload(after),
                status=ChangeStatus.PLANNED,
                changed_dimensions=tuple(sorted(canonical)),
                changed_rendered_fields=changed_fields,
                preserved_rendered_fields=preserved_fields,
            )
        )
    return tuple(plans)


def approve_plans(plans: Sequence[UpdatePlan]) -> tuple[UpdatePlan, ...]:
    return tuple(item.with_status(ChangeStatus.APPROVED) for item in plans)


def reject_plans(plans: Sequence[UpdatePlan]) -> tuple[UpdatePlan, ...]:
    return tuple(item.with_status(ChangeStatus.REJECTED) for item in plans)


def snapshot_hashes(profiles: Sequence[RoleProfile]) -> dict[str, dict[str, str]]:
    return {item.id: hash_all_sections(item) for item in profiles}


def apply_approved_plans(
    plans: Sequence[UpdatePlan],
    profiles: Sequence[RoleProfile],
    dependency_graph: DependencyGraph,
    *,
    new_level: LevelDefinition,
    expected_before: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[tuple[RoleProfile, ...], DependencyGraph, PreservationReport, tuple[UpdatePlan, ...]]:
    before = expected_before or snapshot_hashes(profiles)
    by_id = {item.id: item for item in profiles}
    applied_ids: set[str] = set()
    finished: list[UpdatePlan] = []
    intended: dict[tuple[str, str], str] = {}

    for plan in plans:
        if plan.status is ChangeStatus.REJECTED:
            finished.append(plan)
            continue
        if plan.status is not ChangeStatus.APPROVED:
            raise DependencyGraphError(
                f"Cannot apply {plan.status.value} plan for {plan.profile_id}:{plan.section_id}"
            )
        profile = by_id[plan.profile_id]
        current = _as_text(profile.section_value(plan.section_id))
        if current == plan.after:
            finished.append(plan.with_status(ChangeStatus.APPLIED))
            applied_ids.add(plan.profile_id)
            continue
        if current != plan.before:
            raise DependencyGraphError(
                f"Section {plan.section_id} on {plan.profile_id} changed since planning"
            )
        by_id[plan.profile_id] = profile.with_section(plan.section_id, plan.after)
        intended[(plan.profile_id, plan.section_id)] = plan.after
        applied_ids.add(plan.profile_id)
        finished.append(plan.with_status(ChangeStatus.APPLIED))

    updated_profiles = tuple(by_id[item.id] for item in profiles)
    if applied_ids:
        graph = bump_level_edge_versions(
            dependency_graph,
            new_level.id,
            new_level.version,
            applied_ids,
        )
    else:
        graph = dependency_graph

    after = snapshot_hashes(updated_profiles)
    report = compare_preservation(before, after, intended)
    field_violations = _dimension_violations(plans, before_profiles=profiles, after_profiles=updated_profiles)
    if field_violations:
        report = PreservationReport(
            changed_sections=report.changed_sections,
            unchanged_sections=report.unchanged_sections,
            violations=report.violations + field_violations,
        )
    if not report.ok:
        raise DependencyGraphError("Preservation verification failed: " + "; ".join(report.violations))
    return updated_profiles, graph, report, tuple(finished)


def compare_preservation(
    before: Mapping[str, Mapping[str, str]],
    after: Mapping[str, Mapping[str, str]],
    intended: Mapping[tuple[str, str], str],
) -> PreservationReport:
    changed: list[SectionHash] = []
    unchanged: list[SectionHash] = []
    violations: list[str] = []
    intended_keys = set(intended)
    for profile_id, sections in before.items():
        after_sections = after.get(profile_id)
        if after_sections is None:
            violations.append(f"Profile {profile_id} disappeared during apply")
            continue
        for section_id in PROFILE_SECTION_IDS:
            old = sections[section_id]
            new = after_sections[section_id]
            key = (profile_id, section_id)
            if key in intended_keys:
                if old == new:
                    violations.append(
                        f"Expected {profile_id}:{section_id} to change, but the hash is unchanged"
                    )
                changed.append(SectionHash(profile_id, section_id, new))
            elif old != new:
                violations.append(f"Unexpected change in {profile_id}:{section_id}")
            else:
                unchanged.append(SectionHash(profile_id, section_id, new))
    return PreservationReport(
        changed_sections=tuple(changed),
        unchanged_sections=tuple(unchanged),
        violations=tuple(violations),
    )


def _dimension_violations(
    plans: Sequence[UpdatePlan],
    *,
    before_profiles: Sequence[RoleProfile],
    after_profiles: Sequence[RoleProfile],
) -> tuple[str, ...]:
    before_by_id = {item.id: item for item in before_profiles}
    after_by_id = {item.id: item for item in after_profiles}
    violations: list[str] = []
    for plan in plans:
        if plan.status is ChangeStatus.REJECTED:
            continue
        allowed = plan.changed_rendered_fields
        if not allowed:
            continue
        before_text = _as_text(before_by_id[plan.profile_id].section_value(plan.section_id))
        after_text = _as_text(after_by_id[plan.profile_id].section_value(plan.section_id))
        for item in field_preservation_violations(before_text, after_text, allowed):
            violations.append(f"{plan.profile_id}:{plan.section_id}: {item}")
    return tuple(violations)
