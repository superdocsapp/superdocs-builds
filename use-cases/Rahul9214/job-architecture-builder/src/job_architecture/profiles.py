"""Employee-readable role profiles and review artifacts.

Strong-fit roles get a full profile. Provisional roles with a family and
level get a profile marked provisional. Hybrid, sparse, and misfit roles
are review artifacts, not silently normalized profiles.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_architecture.catalog import FAMILY_BY_ID, LEVEL_BY_LABEL, LEVEL_DEFINITIONS
from job_architecture.matrices import FamilyCompetencyMatrix, competency_ids_for_profile
from job_architecture.models import (
    FitStatus,
    LevelDefinition,
    MisfitReason,
    RoleAssessment,
    RoleEvidence,
    RoleProfile,
)
from job_architecture.textutil import UNSTATED


@dataclass(frozen=True)
class ReviewArtifact:
    """Honest exclusion or provisional-review record. Not a finalized profile."""

    role_id: str
    title: str
    fit_status: FitStatus
    summary: str
    reasons: tuple[MisfitReason, ...]
    supporting_evidence: tuple[str, ...]


def render_level_expectations(level: LevelDefinition) -> str:
    decision = level.decision_authority or level.autonomy
    complexity = level.complexity or "Matches the published complexity of this level."
    lines = [
        f"{level.label} (definition version {level.version})",
        f"Scope: {level.scope}",
        f"Autonomy / decision authority: {decision}",
        f"Complexity: {complexity}",
        f"Impact: {level.impact}",
        f"Leadership: {level.leadership}",
    ]
    if level.people_management:
        lines.append(f"People-management expectations: {level.people_management}")
    return "\n".join(lines)


def render_progression(level: LevelDefinition, levels: tuple[LevelDefinition, ...]) -> str:
    same_track = [item for item in levels if item.track_id == level.track_id]
    nxt = next((item for item in same_track if item.rank == level.rank + 1), None)
    if nxt is None:
        return (
            f"{level.label} is the highest published level on this track. "
            "Progression is through broader impact inside the same level definition."
        )
    return (
        f"The next published level on this track is {nxt.label}. "
        "Growth means expanding scope, autonomy, and impact toward that level's "
        "canonical definition without copying its wording here."
    )


def _purpose(evidence: RoleEvidence) -> str:
    if evidence.domain_depth and evidence.domain_depth != UNSTATED:
        first = evidence.domain_depth.strip().split("\n")[0].strip()
        if first:
            return first
    if evidence.responsibilities:
        return evidence.responsibilities[0]
    return f"This role contributes within {evidence.organization}."


def _scope_decision(evidence: RoleEvidence) -> str:
    parts = [
        f"Scope: {evidence.scope}" if evidence.scope != UNSTATED else "",
        f"Autonomy: {evidence.autonomy}" if evidence.autonomy != UNSTATED else "",
    ]
    if evidence.decision_making_authority:
        parts.append(f"Decision making: {evidence.decision_making_authority}")
    text = "\n".join(part for part in parts if part)
    return text or "Scope and decision making are not stated in the source job description."


def _competency_section(matrix: FamilyCompetencyMatrix, competency_ids: tuple[str, ...]) -> str:
    names = []
    for competency_id in competency_ids:
        try:
            names.append(matrix.competency(competency_id).name)
        except KeyError:
            continue
    if not names:
        return "No family competencies were assigned."
    return "Core competencies: " + "; ".join(names) + "."


def _evidence_note(assessment: RoleAssessment) -> str:
    status = assessment.fit_status.value
    if assessment.fit_status is FitStatus.PROVISIONAL:
        return (
            f"Classification is {status} and is not finalized. "
            "Title text did not set family, track, or level."
        )
    return (
        f"Classification is {status}. Family, track, and level come from role evidence, not the title."
    )


def profile_id_for(role_id: str) -> str:
    return f"profile-{role_id}"


def generate_role_profile(
    evidence: RoleEvidence,
    assessment: RoleAssessment,
    *,
    matrix: FamilyCompetencyMatrix,
    levels: tuple[LevelDefinition, ...] | None = None,
) -> RoleProfile:
    catalog = levels or LEVEL_DEFINITIONS
    if not assessment.proposed_family or not assessment.proposed_level or not assessment.proposed_track:
        raise ValueError("classified profiles require family, track, and level")
    level = LEVEL_BY_LABEL.get(assessment.proposed_level)
    if level is None:
        raise ValueError(f"unknown level label {assessment.proposed_level!r}")
    family = FAMILY_BY_ID[assessment.proposed_family]
    track_name = (
        "Individual Contributor"
        if assessment.proposed_track == "individual_contributor"
        else "People Manager"
    )
    draft = RoleProfile(
        id=profile_id_for(evidence.role_id),
        role_id=evidence.role_id,
        family_id=family.id,
        track_id=assessment.proposed_track,
        level_id=level.id,
        display_title=evidence.title,
        summary=_purpose(evidence),
        responsibilities=list(evidence.responsibilities) or ["Responsibilities were not listed."],
        competency_ids=[],
        family_name=family.name,
        track_name=track_name,
        level_label=level.label,
        classification=assessment.fit_status.value,
        scope_decision_making=_scope_decision(evidence),
        core_competencies="",
        level_expectations=render_level_expectations(level),
        progression=render_progression(level, catalog),
        evidence_note=_evidence_note(assessment),
    )
    competency_ids = competency_ids_for_profile(matrix, draft)
    return RoleProfile(
        **{
            **draft.to_dict(),
            "competency_ids": list(competency_ids),
            "core_competencies": _competency_section(matrix, competency_ids),
        }
    )


def generate_review_artifact(evidence: RoleEvidence, assessment: RoleAssessment) -> ReviewArtifact:
    if assessment.fit_status is FitStatus.MISFIT:
        summary = "This role is a misfit and is not published as a normalized family/level profile."
    else:
        summary = "This role remains provisional and is not published as a finalized profile."
    return ReviewArtifact(
        role_id=evidence.role_id,
        title=evidence.title,
        fit_status=assessment.fit_status,
        summary=summary,
        reasons=tuple(assessment.misfit_reasons),
        supporting_evidence=tuple(assessment.supporting_evidence),
    )
