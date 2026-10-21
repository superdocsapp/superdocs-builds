"""Per-family competency matrices derived from occupied families and levels.

Competencies are a constrained catalog (craft, ownership, judgment,
collaboration, influence, and people leadership when managers exist).
Indicators come from canonical level definitions, not invented role-specific
skills.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_architecture.catalog import FAMILY_BY_ID, LEVEL_DEFINITIONS
from job_architecture.models import Competency, JobFamily, LevelDefinition, RoleAssessment, RoleProfile


@dataclass(frozen=True)
class FamilyCompetencyMatrix:
    family_id: str
    family_name: str
    competencies: tuple[Competency, ...]
    evidence_limited: bool
    limitation: str

    def competency(self, competency_id: str) -> Competency:
        for item in self.competencies:
            if item.id == competency_id:
                return item
        raise KeyError(competency_id)


_CRAFT = (
    "craft_execution",
    "Craft execution",
    "Delivers the family's core work to the standard of the assigned level.",
)
_OWNERSHIP = (
    "scope_ownership",
    "Scope ownership",
    "Owns outcomes at the scope published for the assigned level.",
)
_JUDGMENT = (
    "judgment",
    "Judgment and decision quality",
    "Makes decisions at the autonomy published for the assigned level.",
)
_COLLAB = (
    "collaboration",
    "Stakeholder collaboration",
    "Works with the stakeholder breadth expected at the assigned level.",
)
_INFLUENCE = (
    "influence",
    "Craft influence",
    "Leads through review, standards, or coaching at the assigned level.",
)
_PEOPLE = (
    "people_leadership",
    "People leadership",
    "Hires, coaches, and is accountable for direct reports at the assigned management level.",
)


def _indicators_for(level: LevelDefinition) -> list[str]:
    decision = level.decision_authority or level.autonomy
    complexity = level.complexity or "Work complexity matches the published level."
    items = [
        f"Scope: {level.scope}",
        f"Autonomy / decision authority: {decision}",
        f"Complexity: {complexity}",
        f"Impact: {level.impact}",
        f"Leadership: {level.leadership}",
    ]
    if level.people_management:
        items.append(f"People management: {level.people_management}")
    return items


def build_competency_matrices(
    families: tuple[JobFamily, ...],
    assessments: tuple[RoleAssessment, ...],
    *,
    levels: tuple[LevelDefinition, ...] | None = None,
) -> tuple[FamilyCompetencyMatrix, ...]:
    catalog = levels or LEVEL_DEFINITIONS
    occupied: dict[str, list[RoleAssessment]] = {}
    for item in assessments:
        if item.proposed_family:
            occupied.setdefault(item.proposed_family, []).append(item)

    matrices: list[FamilyCompetencyMatrix] = []
    for family in families:
        members = occupied.get(family.id, [])
        classified = [item for item in members if item.proposed_level]
        labels = {item.proposed_level for item in classified if item.proposed_level}
        used_levels = tuple(level for level in catalog if level.label in labels) or catalog
        has_managers = any(item.proposed_track == "people_manager" for item in classified)
        specs = [_CRAFT, _OWNERSHIP, _JUDGMENT, _COLLAB, _INFLUENCE]
        if has_managers:
            specs = [*specs, _PEOPLE]
        competencies = tuple(
            Competency(
                id=f"{family.id}-{slug}",
                family_id=family.id,
                name=name,
                description=f"{description} Family context: {family.description}",
                indicators_by_level={
                    level.id: _indicators_for(level) for level in used_levels
                },
            )
            for slug, name, description in specs
        )
        limited = len(classified) < 2
        limitation = (
            "Fewer than two classified roles occupy this family, so the matrix stays generic."
            if limited
            else ""
        )
        matrices.append(
            FamilyCompetencyMatrix(
                family_id=family.id,
                family_name=family.name if family.id in FAMILY_BY_ID else family.name,
                competencies=competencies,
                evidence_limited=limited,
                limitation=limitation,
            )
        )
    return tuple(matrices)


def competency_ids_for_profile(
    matrix: FamilyCompetencyMatrix,
    profile: RoleProfile,
) -> tuple[str, ...]:
    ids = [item.id for item in matrix.competencies]
    if profile.track_id != "people_manager":
        ids = [item for item in ids if not item.endswith("-people_leadership")]
    return tuple(ids)
