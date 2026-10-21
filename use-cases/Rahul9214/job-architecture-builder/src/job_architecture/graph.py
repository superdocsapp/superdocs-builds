"""Explicit dependency graph from canonical definitions to profile sections."""

from __future__ import annotations

from dataclasses import dataclass, replace

from job_architecture.matrices import FamilyCompetencyMatrix
from job_architecture.models import (
    PROFILE_SECTION_IDS,
    DependencyEdge,
    LevelDefinition,
    RoleProfile,
)


class DependencyGraphError(ValueError):
    """The graph is missing, dangling, or inconsistent."""


SOURCE_LEVEL = "level_definition"
SOURCE_COMPETENCY = "competency"
TARGET_PROFILE = "role_profile"
SECTION_LEVEL_EXPECTATIONS = "level_expectations"
SECTION_CORE_COMPETENCIES = "core_competencies"


@dataclass(frozen=True)
class DependencyGraph:
    edges: tuple[DependencyEdge, ...]

    def for_source(self, source_type: str, source_id: str) -> tuple[DependencyEdge, ...]:
        return tuple(
            edge
            for edge in self.edges
            if edge.source_type == source_type and edge.source_id == source_id
        )

    def for_profile(self, profile_id: str) -> tuple[DependencyEdge, ...]:
        return tuple(edge for edge in self.edges if edge.target_id == profile_id)


def _edge_id(source_type: str, source_id: str, target_id: str, section: str) -> str:
    return f"{source_type}:{source_id}->{target_id}:{section}"


def build_dependency_graph(
    profiles: tuple[RoleProfile, ...],
    levels: tuple[LevelDefinition, ...],
    matrices: tuple[FamilyCompetencyMatrix, ...],
) -> DependencyGraph:
    level_by_id = {item.id: item for item in levels}
    competency_ids = {
        competency.id
        for matrix in matrices
        for competency in matrix.competencies
    }
    edges: list[DependencyEdge] = []
    for profile in profiles:
        level = level_by_id.get(profile.level_id)
        if level is None:
            raise DependencyGraphError(
                f"Profile {profile.id} depends on unknown level {profile.level_id}"
            )
        edges.append(
            DependencyEdge(
                id=_edge_id(SOURCE_LEVEL, level.id, profile.id, SECTION_LEVEL_EXPECTATIONS),
                source_type=SOURCE_LEVEL,
                source_id=level.id,
                target_type=TARGET_PROFILE,
                target_id=profile.id,
                target_section=SECTION_LEVEL_EXPECTATIONS,
                notes="Level-expectations prose is generated from the canonical level definition.",
                source_version=level.version,
            )
        )
        for competency_id in profile.competency_ids:
            if competency_id not in competency_ids:
                raise DependencyGraphError(
                    f"Profile {profile.id} references unknown competency {competency_id}"
                )
            edges.append(
                DependencyEdge(
                    id=_edge_id(SOURCE_COMPETENCY, competency_id, profile.id, SECTION_CORE_COMPETENCIES),
                    source_type=SOURCE_COMPETENCY,
                    source_id=competency_id,
                    target_type=TARGET_PROFILE,
                    target_id=profile.id,
                    target_section=SECTION_CORE_COMPETENCIES,
                    notes="Core-competency section lists family matrix competencies.",
                    source_version=1,
                )
            )
    graph = DependencyGraph(edges=tuple(edges))
    validate_dependency_graph(graph, profiles, levels)
    return graph


def validate_dependency_graph(
    graph: DependencyGraph,
    profiles: tuple[RoleProfile, ...] | list[RoleProfile],
    levels: tuple[LevelDefinition, ...] | list[LevelDefinition],
) -> None:
    profile_ids = {item.id for item in profiles}
    level_ids = {item.id for item in levels}
    seen_ids: set[str] = set()
    for edge in graph.edges:
        if edge.id in seen_ids:
            raise DependencyGraphError(f"Duplicate dependency id {edge.id}")
        seen_ids.add(edge.id)
        if edge.target_type != TARGET_PROFILE:
            raise DependencyGraphError(f"Unsupported target_type {edge.target_type}")
        if edge.target_id not in profile_ids:
            raise DependencyGraphError(f"Dangling profile target {edge.target_id}")
        if edge.target_section not in PROFILE_SECTION_IDS:
            raise DependencyGraphError(f"Unknown target_section {edge.target_section}")
        if edge.source_type == SOURCE_LEVEL and edge.source_id not in level_ids:
            raise DependencyGraphError(f"Dangling level source {edge.source_id}")
        if edge.source_type not in {SOURCE_LEVEL, SOURCE_COMPETENCY}:
            raise DependencyGraphError(f"Unsupported source_type {edge.source_type}")


def bump_level_edge_versions(
    graph: DependencyGraph,
    level_id: str,
    new_version: int,
    profile_ids: set[str],
) -> DependencyGraph:
    updated: list[DependencyEdge] = []
    for edge in graph.edges:
        if (
            edge.source_type == SOURCE_LEVEL
            and edge.source_id == level_id
            and edge.target_id in profile_ids
            and edge.target_section == SECTION_LEVEL_EXPECTATIONS
        ):
            updated.append(replace(edge, source_version=new_version))
        else:
            updated.append(edge)
    return DependencyGraph(edges=tuple(updated))
