"""Canonical framework aggregate generated from architecture-domain objects."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from job_architecture.architecture import ArchitectureResult
from job_architecture.catalog import LEVEL_DEFINITIONS
from job_architecture.graph import DependencyGraph, build_dependency_graph
from job_architecture.matrices import FamilyCompetencyMatrix, build_competency_matrices
from job_architecture.models import (
    CareerTrack,
    FitStatus,
    JobFamily,
    LevelDefinition,
    RoleEvidence,
    RoleProfile,
)
from job_architecture.profiles import ReviewArtifact, generate_review_artifact, generate_role_profile

FRAMEWORK_PRINCIPLES = (
    "Titles never determine family, track, or level.",
    "Assignments require role evidence across published dimensions.",
    "Insufficient, hybrid, or out-of-architecture evidence stays provisional or misfit.",
    "Canonical level changes reach profiles only through explicit dependency edges.",
)

_COMPLEXITY_BY_LABEL = {
    "IC1": "Straightforward, well-specified tasks with limited edge cases.",
    "IC2": "Routine component work with some local edge cases.",
    "IC3": "Non-trivial trade-offs inside a named service, product area, or book of work.",
    "IC4": "Cross-team problems with incomplete information and multi-quarter bets.",
    "IC5": "Ambiguous organization-wide problems with competing constraints.",
    "M1": "Team-level people and delivery trade-offs for a single reporting group.",
    "M2": "Multi-team people and delivery trade-offs, including manager development.",
    "M3": "Function-wide people strategy and organizational-shape decisions.",
}


@dataclass(frozen=True)
class RoleMapping:
    role_id: str
    fit_status: FitStatus
    family_id: str | None
    track_id: str | None
    level_id: str | None
    profile_id: str | None


@dataclass(frozen=True)
class FrameworkDocument:
    organization: str
    purpose: str
    principles: tuple[str, ...]
    tracks: tuple[CareerTrack, ...]
    levels: tuple[LevelDefinition, ...]
    families: tuple[JobFamily, ...]
    competency_matrices: tuple[FamilyCompetencyMatrix, ...]
    role_mappings: tuple[RoleMapping, ...]
    profiles: tuple[RoleProfile, ...]
    provisional_roles: tuple[ReviewArtifact, ...]
    misfits: tuple[ReviewArtifact, ...]
    dependency_graph: DependencyGraph

    def profile(self, profile_id: str) -> RoleProfile:
        for item in self.profiles:
            if item.id == profile_id:
                return item
        raise KeyError(profile_id)

    def level(self, level_id: str) -> LevelDefinition:
        for item in self.levels:
            if item.id == level_id or item.label == level_id:
                return item
        raise KeyError(level_id)

    def profiles_for_level(self, level_id: str) -> tuple[RoleProfile, ...]:
        level = self.level(level_id)
        return tuple(item for item in self.profiles if item.level_id == level.id)

    def with_profiles(self, profiles: Sequence[RoleProfile]) -> FrameworkDocument:
        return replace(self, profiles=tuple(profiles))

    def with_graph(self, graph: DependencyGraph) -> FrameworkDocument:
        return replace(self, dependency_graph=graph)

    def with_level(self, level: LevelDefinition) -> FrameworkDocument:
        levels = tuple(level if item.id == level.id else item for item in self.levels)
        return replace(self, levels=levels)


def enrich_level(level: LevelDefinition) -> LevelDefinition:
    complexity = level.complexity or _COMPLEXITY_BY_LABEL.get(level.label, "")
    decision = level.decision_authority or level.autonomy
    if complexity == level.complexity and decision == level.decision_authority:
        return level
    return replace(level, complexity=complexity, decision_authority=decision)


def generate_framework(
    architecture: ArchitectureResult,
    evidences: Sequence[RoleEvidence],
) -> FrameworkDocument:
    evidence_by_id: Mapping[str, RoleEvidence] = {item.role_id: item for item in evidences}
    levels = tuple(enrich_level(item) for item in architecture.levels or LEVEL_DEFINITIONS)
    matrices = build_competency_matrices(
        architecture.families,
        architecture.assessments,
        levels=levels,
    )
    matrix_by_family = {item.family_id: item for item in matrices}

    profiles: list[RoleProfile] = []
    provisional_artifacts: list[ReviewArtifact] = []
    misfit_artifacts: list[ReviewArtifact] = []
    mappings: list[RoleMapping] = []

    for assessment in architecture.assessments:
        evidence = evidence_by_id[assessment.role_id]
        classified = bool(
            assessment.proposed_family and assessment.proposed_track and assessment.proposed_level
        )
        if classified:
            matrix = matrix_by_family[assessment.proposed_family]
            profile = generate_role_profile(
                evidence,
                assessment,
                matrix=matrix,
                levels=levels,
            )
            profiles.append(profile)
            mappings.append(
                RoleMapping(
                    role_id=assessment.role_id,
                    fit_status=assessment.fit_status,
                    family_id=assessment.proposed_family,
                    track_id=assessment.proposed_track,
                    level_id=profile.level_id,
                    profile_id=profile.id,
                )
            )
            continue

        artifact = generate_review_artifact(evidence, assessment)
        mappings.append(
            RoleMapping(
                role_id=assessment.role_id,
                fit_status=assessment.fit_status,
                family_id=assessment.proposed_family,
                track_id=assessment.proposed_track,
                level_id=None,
                profile_id=None,
            )
        )
        if assessment.fit_status is FitStatus.MISFIT:
            misfit_artifacts.append(artifact)
        else:
            provisional_artifacts.append(artifact)

    graph = build_dependency_graph(tuple(profiles), levels, matrices)
    return FrameworkDocument(
        organization=architecture.organization,
        purpose=(
            f"Canonical job architecture for {architecture.organization}, "
            "generated from role evidence rather than title matching."
        ),
        principles=FRAMEWORK_PRINCIPLES,
        tracks=architecture.tracks,
        levels=levels,
        families=architecture.families,
        competency_matrices=matrices,
        role_mappings=tuple(mappings),
        profiles=tuple(profiles),
        provisional_roles=tuple(provisional_artifacts),
        misfits=tuple(misfit_artifacts),
        dependency_graph=graph,
    )
