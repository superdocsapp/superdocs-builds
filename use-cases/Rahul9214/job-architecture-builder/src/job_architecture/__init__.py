"""Job-architecture domain models, evidence clustering, framework generation.

Domain reasoning does not call SuperDocs or invoke an AI model. SuperDocs
HTTP lives in job_architecture.superdocs and is unused by framework generation.
"""

from job_architecture.architecture import ArchitectureResult, build_architecture
from job_architecture.assess import assess_role
from job_architecture.cluster import ClusteringResult, cluster_corpus, evidence_signature
from job_architecture.evidence import extract_role_evidence, evidence_from_markdown
from job_architecture.framework import FrameworkDocument, generate_framework
from job_architecture.models import (
    CareerTrack,
    CareerTrackKind,
    Competency,
    DependencyEdge,
    FitStatus,
    JobFamily,
    LevelDefinition,
    MisfitReason,
    RoleAssessment,
    RoleEvidence,
    RoleProfile,
    SourceReference,
)
from job_architecture.propagation import (
    ChangeStatus,
    ImpactAnalysis,
    PreservationReport,
    UpdatePlan,
    analyze_level_change,
    apply_approved_plans,
    plan_level_updates,
)

__all__ = [
    "ArchitectureResult",
    "CareerTrack",
    "CareerTrackKind",
    "ChangeStatus",
    "ClusteringResult",
    "Competency",
    "DependencyEdge",
    "FitStatus",
    "FrameworkDocument",
    "ImpactAnalysis",
    "JobFamily",
    "LevelDefinition",
    "MisfitReason",
    "PreservationReport",
    "RoleAssessment",
    "RoleEvidence",
    "RoleProfile",
    "SourceReference",
    "UpdatePlan",
    "analyze_level_change",
    "apply_approved_plans",
    "assess_role",
    "build_architecture",
    "cluster_corpus",
    "evidence_from_markdown",
    "evidence_signature",
    "extract_role_evidence",
    "generate_framework",
    "plan_level_updates",
]
