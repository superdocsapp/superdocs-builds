"""Run the architecture engine over a set of roles. No network, no SuperDocs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from job_architecture.assess import assess_role
from job_architecture.catalog import CAREER_TRACKS, JOB_FAMILIES, LEVEL_DEFINITIONS
from job_architecture.cluster import ClusteringResult, RoleCluster, cluster_corpus
from job_architecture.evidence import extract_role_evidence
from job_architecture.fixtures import LoadedCorpus, ParsedJobDescription
from job_architecture.models import (
    CareerTrack,
    FitStatus,
    JobFamily,
    LevelDefinition,
    RoleAssessment,
    RoleEvidence,
)


@dataclass(frozen=True)
class ArchitectureResult:
    organization: str
    assessments: tuple[RoleAssessment, ...]
    families: tuple[JobFamily, ...]
    clusters: tuple[RoleCluster, ...]
    clustering: ClusteringResult
    tracks: tuple[CareerTrack, ...]
    levels: tuple[LevelDefinition, ...]
    provisional_role_ids: tuple[str, ...]
    misfit_role_ids: tuple[str, ...]
    unclustered_role_ids: tuple[str, ...]
    bridge_role_ids: tuple[str, ...]

    def assessment_for(self, role_id: str) -> RoleAssessment:
        for item in self.assessments:
            if item.role_id == role_id:
                return item
        raise KeyError(role_id)


def assess_evidence_set(
    evidences: Sequence[RoleEvidence],
    *,
    organization: str,
    raw_by_role_id: dict[str, str] | None = None,
) -> ArchitectureResult:
    raw_by_role_id = raw_by_role_id or {}
    assessments = tuple(
        assess_role(item, raw_markdown=raw_by_role_id.get(item.role_id))
        for item in evidences
    )
    clustering = cluster_corpus(evidences, assessments)
    used_families = {item.proposed_family for item in assessments if item.proposed_family}
    used_families |= {item.proposed_family for item in clustering.clusters if item.proposed_family}
    families = tuple(family for family in JOB_FAMILIES if family.id in used_families) or JOB_FAMILIES
    provisional = tuple(
        item.role_id for item in assessments if item.fit_status is FitStatus.PROVISIONAL
    )
    misfits = tuple(item.role_id for item in assessments if item.fit_status is FitStatus.MISFIT)
    return ArchitectureResult(
        organization=organization,
        assessments=assessments,
        families=families,
        clusters=clustering.clusters,
        clustering=clustering,
        tracks=CAREER_TRACKS,
        levels=LEVEL_DEFINITIONS,
        provisional_role_ids=provisional,
        misfit_role_ids=misfits,
        unclustered_role_ids=clustering.unclustered_role_ids,
        bridge_role_ids=clustering.bridge_role_ids,
    )


def extract_corpus_evidence(corpus: LoadedCorpus) -> tuple[RoleEvidence, ...]:
    organization = corpus.manifest.organization
    return tuple(
        extract_role_evidence(parsed, organization) for parsed in corpus.job_descriptions
    )


def build_architecture(corpus: LoadedCorpus) -> ArchitectureResult:
    evidences = extract_corpus_evidence(corpus)
    raw = {parsed.role_id: parsed.raw_markdown for parsed in corpus.job_descriptions}
    return assess_evidence_set(
        evidences,
        organization=corpus.manifest.organization,
        raw_by_role_id=raw,
    )


def evidence_for(
    parsed: ParsedJobDescription,
    organization: str,
) -> RoleEvidence:
    return extract_role_evidence(parsed, organization)
