"""JSON views over domain objects. No architecture reasoning."""

from __future__ import annotations

from typing import Any

from job_architecture.architecture import ArchitectureResult
from job_architecture.cluster import RoleCluster
from job_architecture.fixtures import LoadedCorpus
from job_architecture.framework import FrameworkDocument
from job_architecture.models import LevelDefinition, RoleAssessment, RoleEvidence, RoleProfile
from job_architecture.profiles import ReviewArtifact
from job_architecture.propagation import ImpactAnalysis, PreservationReport, UpdatePlan
from job_architecture.web.store import ReviewSession


def corpus_summary(corpus: LoadedCorpus, *, analyzed: bool) -> dict[str, Any]:
    return {
        "corpus_id": corpus.manifest.corpus_id,
        "organization": corpus.manifest.organization,
        "description": corpus.manifest.description,
        "role_count": len(corpus.manifest.roles),
        "analyzed": analyzed,
        "roles": [
            {
                "role_id": role.id,
                "title": role.title,
                "team": role.team,
                "filename": role.file,
            }
            for role in corpus.manifest.roles
        ],
    }


def architecture_summary(arch: ArchitectureResult, corpus: LoadedCorpus) -> dict[str, Any]:
    strong = sum(1 for item in arch.assessments if item.fit_status.value == "strong_fit")
    titles = {role.id: role.title for role in corpus.manifest.roles}
    return {
        "corpus_id": corpus.manifest.corpus_id,
        "organization": arch.organization,
        "metrics": {
            "total_roles": len(arch.assessments),
            "proposed_families": len(arch.families),
            "tracks": len(arch.tracks),
            "strong_fits": strong,
            "provisional": len(arch.provisional_role_ids),
            "misfits": len(arch.misfit_role_ids),
            "unclustered": len(arch.unclustered_role_ids),
            "bridge_roles": len(arch.bridge_role_ids),
        },
        "families": [item.to_dict() for item in arch.families],
        "tracks": [item.to_dict() for item in arch.tracks],
        "clusters": [cluster_dict(item, titles) for item in arch.clusters],
        "unclustered_role_ids": list(arch.unclustered_role_ids),
        "bridge_role_ids": list(arch.bridge_role_ids),
        "title_conflicts": title_conflict_roles(arch, corpus),
    }


def cluster_dict(cluster: RoleCluster, titles: dict[str, str]) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id,
        "proposed_family": cluster.proposed_family,
        "member_role_ids": list(cluster.member_role_ids),
        "members": [
            {
                "role_id": member.role_id,
                "title": titles.get(member.role_id) or member.role_id,
                "cohesion": member.cohesion,
                "nearest_other_cluster_id": member.nearest_other_cluster_id,
                "nearest_other_similarity": member.nearest_other_similarity,
                "is_ambiguous": member.is_ambiguous,
            }
            for member in cluster.members
        ],
        "cohesion": cluster.cohesion,
        "nearest_cluster_id": cluster.nearest_cluster_id,
        "nearest_cluster_similarity": cluster.nearest_cluster_similarity,
        "separation": cluster.separation,
        "ambiguous_role_ids": list(cluster.ambiguous_role_ids),
        "label_confidence": cluster.label_confidence,
        "notes": cluster.notes,
    }


def role_detail(
    *,
    corpus: LoadedCorpus,
    evidence: RoleEvidence,
    assessment: RoleAssessment,
    arch: ArchitectureResult,
    framework: FrameworkDocument | None,
) -> dict[str, Any]:
    manifest_role = next((item for item in corpus.manifest.roles if item.id == evidence.role_id), None)
    cluster = arch.clustering.cluster_for_role(evidence.role_id)
    mapping = None
    if framework is not None:
        mapping = next((item for item in framework.role_mappings if item.role_id == evidence.role_id), None)
    return {
        "role_id": evidence.role_id,
        "title": evidence.title,
        "team": evidence.team,
        "organization": evidence.organization,
        "filename": manifest_role.file if manifest_role else None,
        "proposed_family": assessment.proposed_family,
        "career_track": assessment.proposed_track,
        "level": assessment.proposed_level,
        "fit_status": assessment.fit_status.value,
        "confidence": assessment.confidence,
        "supporting_evidence": list(assessment.supporting_evidence),
        "counter_evidence": list(assessment.counter_evidence),
        "misfit_reasons": [item.to_dict() for item in assessment.misfit_reasons],
        "source_references": [item.to_dict() for item in evidence.source_references],
        "signals": {
            "scope": evidence.scope,
            "autonomy": evidence.autonomy,
            "complexity": evidence.complexity,
            "impact": evidence.impact,
            "leadership": evidence.leadership,
            "people_management": evidence.people_management,
            "decision_making_authority": evidence.decision_making_authority,
            "stakeholder_breadth": evidence.stakeholder_breadth,
            "domain_depth": evidence.domain_depth,
        },
        "cluster_id": cluster.cluster_id if cluster else None,
        "profile_id": mapping.profile_id if mapping else None,
        "title_conflict": None if assessment.title_conflict is None else assessment.title_conflict.to_dict(),
    }


def exceptions_payload(arch: ArchitectureResult, corpus: LoadedCorpus, framework: FrameworkDocument) -> dict[str, Any]:
    by_id = {item.role_id: item for item in arch.assessments}
    evidence_titles = {role.id: role.title for role in corpus.manifest.roles}
    bridges = {item.role_id: item for item in arch.clustering.bridges}

    def card(role_id: str, bucket: str) -> dict[str, Any]:
        assessment = by_id[role_id]
        artifact = _artifact_for(framework, role_id)
        bridge = bridges.get(role_id)
        return {
            "role_id": role_id,
            "title": evidence_titles.get(role_id) or (artifact.title if artifact else role_id),
            "bucket": bucket,
            "fit_status": assessment.fit_status.value,
            "confidence": assessment.confidence,
            "proposed_family": assessment.proposed_family,
            "proposed_track": assessment.proposed_track,
            "proposed_level": assessment.proposed_level,
            "why": artifact.summary if artifact else "; ".join(item.summary for item in assessment.misfit_reasons),
            "reasons": [item.to_dict() for item in assessment.misfit_reasons],
            "supporting_evidence": list(
                artifact.supporting_evidence if artifact else assessment.supporting_evidence
            ),
            "counter_evidence": list(assessment.counter_evidence),
            "nearest_cluster_id": bridge.nearest_cluster_id if bridge else None,
            "nearest_similarity": bridge.nearest_similarity if bridge else None,
            "status": "requires_architecture_decision" if bucket == "misfit" else "review",
            "has_normalized_profile": any(
                item.role_id == role_id and item.profile_id for item in framework.role_mappings
            ),
        }

    hybrid_ids = [
        role_id
        for role_id in arch.bridge_role_ids
        if role_id not in arch.misfit_role_ids
    ]
    return {
        "provisional": [card(role_id, "provisional") for role_id in arch.provisional_role_ids],
        "hybrid_bridge": [card(role_id, "hybrid_bridge") for role_id in hybrid_ids],
        "misfit": [card(role_id, "misfit") for role_id in arch.misfit_role_ids],
    }


def framework_payload(framework: FrameworkDocument) -> dict[str, Any]:
    return {
        "organization": framework.organization,
        "purpose": framework.purpose,
        "principles": list(framework.principles),
        "tracks": [item.to_dict() for item in framework.tracks],
        "levels": [level_row(item) for item in framework.levels],
        "families": [item.to_dict() for item in framework.families],
        "competency_matrices": [
            {
                "family_id": matrix.family_id,
                "family_name": matrix.family_name,
                "evidence_limited": matrix.evidence_limited,
                "limitation": matrix.limitation,
                "competencies": [item.to_dict() for item in matrix.competencies],
            }
            for matrix in framework.competency_matrices
        ],
        "role_mappings": [
            {
                "role_id": item.role_id,
                "fit_status": item.fit_status.value,
                "family_id": item.family_id,
                "track_id": item.track_id,
                "level_id": item.level_id,
                "profile_id": item.profile_id,
            }
            for item in framework.role_mappings
        ],
        "provisional_summary": [review_artifact_dict(item) for item in framework.provisional_roles],
        "misfit_summary": [review_artifact_dict(item) for item in framework.misfits],
        "profile_count": len(framework.profiles),
        "default_occupied_level_id": _default_occupied_level(framework),
    }


def level_row(level: LevelDefinition) -> dict[str, Any]:
    payload = level.to_dict()
    payload["autonomy_decision"] = level.decision_authority or level.autonomy
    return payload


def profile_summary(profile: RoleProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.id,
        "role_id": profile.role_id,
        "display_title": profile.display_title,
        "family_id": profile.family_id,
        "family_name": profile.family_name,
        "track_id": profile.track_id,
        "track_name": profile.track_name,
        "level_id": profile.level_id,
        "level_label": profile.level_label,
        "classification": profile.classification,
        "is_provisional": profile.classification == "provisional",
    }


def profile_detail(profile: RoleProfile) -> dict[str, Any]:
    return {
        **profile_summary(profile),
        "role_purpose": profile.summary,
        "responsibilities": list(profile.responsibilities),
        "scope_decision_making": profile.scope_decision_making,
        "core_competencies": profile.core_competencies,
        "level_expectations": profile.level_expectations,
        "progression": profile.progression,
        "source_evidence_note": profile.evidence_note,
        "competency_ids": list(profile.competency_ids),
    }


def review_artifact_dict(item: ReviewArtifact) -> dict[str, Any]:
    return {
        "kind": "review_artifact",
        "role_id": item.role_id,
        "title": item.title,
        "fit_status": item.fit_status.value,
        "summary": item.summary,
        "reasons": [reason.to_dict() for reason in item.reasons],
        "supporting_evidence": list(item.supporting_evidence),
    }


def impact_payload(analysis: ImpactAnalysis, old: LevelDefinition, new: LevelDefinition) -> dict[str, Any]:
    return {
        "level_id": analysis.level_id,
        "level_label": old.label,
        "old_version": analysis.old_dependency_version,
        "new_version": analysis.new_dependency_version,
        "changed_dimensions": list(analysis.changed_dimensions),
        "affected_profiles_count": len(analysis.affected_profile_ids),
        "unaffected_profiles_count": len(analysis.unaffected_profile_ids),
        "affected_profile_ids": list(analysis.affected_profile_ids),
        "unaffected_profile_ids": list(analysis.unaffected_profile_ids),
        "affected_sections": [
            {
                "profile_id": item.profile_id,
                "section_id": item.section_id,
                "reason": item.reason,
                "old_dependency_version": item.old_dependency_version,
                "new_dependency_version": item.new_dependency_version,
                "edge_id": item.edge_id,
            }
            for item in analysis.affected_sections
        ],
        "reason": analysis.reason,
        "old_level": old.to_dict(),
        "new_level": new.to_dict(),
    }


def plan_dict(plan: UpdatePlan) -> dict[str, Any]:
    return {
        "plan_id": _plan_id(plan),
        "profile_id": plan.profile_id,
        "section_id": plan.section_id,
        "before": plan.before,
        "after": plan.after,
        "reason": plan.reason,
        "status": plan.status.value,
        "old_hash": plan.old_hash,
        "new_hash": plan.new_hash,
        "changed_dimensions": list(plan.changed_dimensions),
        "changed_rendered_fields": list(plan.changed_rendered_fields),
        "preserved_rendered_fields": list(plan.preserved_rendered_fields),
        "dependency": plan.dependency.to_dict(),
    }


def review_payload(session: ReviewSession) -> dict[str, Any]:
    return {
        "corpus_id": session.corpus_id,
        "level_id": session.level_id,
        "remote_operation": session.remote_operation,
        "review_outcome": session.review_outcome,
        "mutation_applied": session.mutation_applied,
        "domain_applied": session.domain_applied,
        "decisions": dict(session.decisions),
        "plans": [
            {
                **plan_dict(plan),
                "decision": session.decisions.get(_plan_id(plan)),
            }
            for plan in session.plans
        ],
        "impact": impact_payload(session.analysis, session.old_level, session.new_level),
        "preservation": preservation_payload(session.preservation) if session.preservation else None,
    }


def preservation_payload(report: PreservationReport) -> dict[str, Any]:
    return {
        "ok": report.ok,
        "unrelated_sections_preserved": report.ok,
        "changed_sections": [
            {"profile_id": item.profile_id, "section_id": item.section_id, "digest": item.digest}
            for item in report.changed_sections
        ],
        "unchanged_sections": [
            {"profile_id": item.profile_id, "section_id": item.section_id, "digest": item.digest}
            for item in report.unchanged_sections
        ],
        "violations": list(report.violations),
        "unchanged_section_count": len(report.unchanged_sections),
        "changed_section_count": len(report.changed_sections),
    }


def title_conflict_roles(arch: ArchitectureResult, corpus: LoadedCorpus) -> list[dict[str, Any]]:
    titles = {role.id: role.title for role in corpus.manifest.roles}
    rows: list[dict[str, Any]] = []
    for assessment in arch.assessments:
        if assessment.title_conflict is None:
            continue
        rows.append(
            {
                "role_id": assessment.role_id,
                "title": titles.get(assessment.role_id, assessment.role_id),
                "fit_status": assessment.fit_status.value,
                "proposed_level": assessment.proposed_level,
                "proposed_track": assessment.proposed_track,
                "title_conflict": assessment.title_conflict.to_dict(),
            }
        )
    return rows


def _artifact_for(framework: FrameworkDocument, role_id: str) -> ReviewArtifact | None:
    for item in (*framework.provisional_roles, *framework.misfits):
        if item.role_id == role_id:
            return item
    return None


def _default_occupied_level(framework: FrameworkDocument) -> str | None:
    occupied = {item.level_id for item in framework.profiles}
    for level in framework.levels:
        if level.id in occupied and level.label == "IC4":
            return level.id
    for level in framework.levels:
        if level.id in occupied:
            return level.id
    return None


def _plan_id(plan: UpdatePlan) -> str:
    return f"{plan.profile_id}:{plan.section_id}"
