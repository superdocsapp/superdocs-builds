import pytest

from job_architecture.models import (
    CareerTrack,
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
    round_trip,
)


def _source_ref(**overrides) -> SourceReference:
    payload = {"document_id": "ns-swe-backend", "locator": "Responsibilities", "excerpt": "Own on-call"}
    payload.update(overrides)
    return SourceReference.from_dict(payload)


def _evidence(**overrides) -> RoleEvidence:
    payload = {
        "role_id": "ns-swe-backend",
        "title": "Software Engineer, Backend",
        "organization": "Northstar Systems",
        "team": "Platform Services",
        "responsibilities": ["Build backend services", "Own on-call"],
        "scope": "Two to three platform services",
        "autonomy": "Local technical choices within platform standards",
        "complexity": "Multi-tenant API and data-model work",
        "impact": "Downstream product teams depend on these APIs",
        "leadership": "Mentorship through review, no reports",
        "people_management": "None; no hiring or reviews",
        "stakeholder_breadth": "Product engineering, SRE, security, manager",
        "domain_depth": "Identity and entitlements services",
        "decision_making_authority": "Service-local decisions; interfaces need review",
        "source_references": [_source_ref().to_dict()],
    }
    payload.update(overrides)
    return RoleEvidence.from_dict(payload)


def test_fit_status_accepts_only_declared_values() -> None:
    assert {status.value for status in FitStatus} == {"strong_fit", "provisional", "misfit"}
    with pytest.raises(ValueError, match="fit_status"):
        RoleAssessment.from_dict(
            {
                "role_id": "x",
                "fit_status": "maybe",
                "confidence": 0.5,
            }
        )


def test_role_evidence_requires_all_dimensions() -> None:
    evidence = _evidence()
    serialized = evidence.to_dict()
    for field_name in (
        "responsibilities",
        "scope",
        "autonomy",
        "complexity",
        "impact",
        "leadership",
        "people_management",
        "stakeholder_breadth",
        "domain_depth",
        "source_references",
    ):
        assert field_name in serialized
        assert serialized[field_name] not in (None, "", [])


def test_role_evidence_rejects_empty_required_strings() -> None:
    with pytest.raises(ValueError, match="scope"):
        _evidence(scope="   ")


def test_role_evidence_round_trip() -> None:
    original = _evidence()
    restored = round_trip(original)
    assert restored == original
    assert restored.to_dict() == original.to_dict()


def test_source_reference_requires_locator() -> None:
    with pytest.raises(ValueError, match="locator"):
        SourceReference.from_dict({"document_id": "doc-1", "locator": ""})


def test_job_family_and_career_track_round_trip() -> None:
    family = JobFamily.from_dict(
        {
            "id": "engineering",
            "name": "Engineering",
            "description": "Software design, delivery, and operation.",
            "typical_domains": ["backend", "frontend", "infrastructure"],
        }
    )
    track = CareerTrack.from_dict(
        {
            "id": "engineering-ic",
            "family_id": "engineering",
            "kind": "individual_contributor",
            "name": "Engineering IC",
            "description": "Technical contribution without people management.",
        }
    )
    assert round_trip(family) == family
    assert round_trip(track) == track
    with pytest.raises(ValueError, match="kind"):
        CareerTrack.from_dict(
            {
                "id": "engineering-ic",
                "family_id": "engineering",
                "kind": "tech_lead_plus",
                "name": "Engineering IC",
                "description": "Invalid kind",
            }
        )


def test_level_definition_rank_validation() -> None:
    payload = {
        "id": "eng-ic-l4",
        "family_id": "engineering",
        "track_id": "engineering-ic",
        "label": "L4",
        "rank": 4,
        "scope": "Team-level service ownership",
        "autonomy": "Independent within standards",
        "impact": "Multiple consuming teams",
        "leadership": "Mentorship, no reports",
    }
    level = LevelDefinition.from_dict(payload)
    assert round_trip(level) == level
    with pytest.raises(ValueError, match="rank"):
        LevelDefinition.from_dict({**payload, "rank": -1})
    with pytest.raises(ValueError, match="rank"):
        LevelDefinition.from_dict({**payload, "rank": True})


def test_competency_indicators_round_trip() -> None:
    competency = Competency.from_dict(
        {
            "id": "eng-systems-thinking",
            "family_id": "engineering",
            "name": "Systems thinking",
            "description": "Sees failure modes across services.",
            "indicators_by_level": {
                "eng-ic-l4": ["Identifies cross-service failure modes"],
                "eng-ic-l6": ["Sets platform contracts other teams follow"],
            },
        }
    )
    assert round_trip(competency) == competency
    with pytest.raises(ValueError, match="indicators_by_level"):
        Competency.from_dict(
            {
                "id": "eng-systems-thinking",
                "family_id": "engineering",
                "name": "Systems thinking",
                "description": "Sees failure modes across services.",
                "indicators_by_level": {"eng-ic-l4": [""]},
            }
        )


def test_role_assessment_strong_fit_requires_family() -> None:
    with pytest.raises(ValueError, match="proposed_family"):
        RoleAssessment.from_dict(
            {
                "role_id": "ns-swe-backend",
                "fit_status": "strong_fit",
                "confidence": 0.9,
            }
        )


def test_role_assessment_misfit_requires_reason() -> None:
    with pytest.raises(ValueError, match="misfit"):
        RoleAssessment.from_dict(
            {
                "role_id": "ns-developer-advocate",
                "fit_status": "misfit",
                "confidence": 0.8,
                "misfit_reasons": [],
            }
        )


def test_role_assessment_provisional_allows_omitted_level() -> None:
    assessment = RoleAssessment.from_dict(
        {
            "role_id": "ns-program-coordinator",
            "fit_status": "provisional",
            "confidence": 0.2,
            "proposed_family": None,
            "proposed_track": None,
            "proposed_level": None,
            "supporting_evidence": ["Title is Program Coordinator"],
            "counter_evidence": ["Responsibilities are generic duties as assigned"],
            "misfit_reasons": [
                {
                    "code": "insufficient_evidence",
                    "summary": "Description is too thin to defend a family.",
                    "detail": "Scope and stakeholders are unspecified.",
                    "source_references": [
                        {"document_id": "ns-program-coordinator", "locator": "Role purpose"}
                    ],
                }
            ],
        }
    )
    restored = round_trip(assessment)
    assert restored.proposed_level is None
    assert restored.fit_status is FitStatus.PROVISIONAL
    assert restored.misfit_reasons[0].code == "insufficient_evidence"


def test_role_assessment_confidence_bounds() -> None:
    base = {
        "role_id": "ns-swe-backend",
        "fit_status": "strong_fit",
        "proposed_family": "engineering",
        "confidence": 0.0,
    }
    assert RoleAssessment.from_dict(base).confidence == 0.0
    assert RoleAssessment.from_dict({**base, "confidence": 1}).confidence == 1.0
    with pytest.raises(ValueError, match="confidence"):
        RoleAssessment.from_dict({**base, "confidence": 1.01})
    with pytest.raises(ValueError, match="confidence"):
        RoleAssessment.from_dict({**base, "confidence": True})


def test_misfit_role_assessment_round_trip() -> None:
    assessment = RoleAssessment.from_dict(
        {
            "role_id": "ns-developer-advocate",
            "fit_status": "misfit",
            "confidence": 0.86,
            "supporting_evidence": ["Success is measured by community reach and content output"],
            "counter_evidence": ["No production service or customer-account ownership"],
            "misfit_reasons": [
                {
                    "code": "outside_architecture",
                    "summary": "Community advocacy sits outside standard families.",
                }
            ],
        }
    )
    assert round_trip(assessment) == assessment


def test_role_profile_and_dependency_edge_round_trip() -> None:
    profile = RoleProfile.from_dict(
        {
            "id": "profile-ns-swe-backend",
            "role_id": "ns-swe-backend",
            "family_id": "engineering",
            "track_id": "engineering-ic",
            "level_id": "eng-ic-l4",
            "display_title": "Software Engineer, Backend",
            "summary": "Builds platform APIs used by product teams.",
            "responsibilities": ["Implement backend services", "Own on-call"],
            "competency_ids": ["eng-systems-thinking"],
        }
    )
    edge = DependencyEdge.from_dict(
        {
            "id": "edge-level-to-profile",
            "source_type": "level_definition",
            "source_id": "eng-ic-l4",
            "target_type": "role_profile",
            "target_id": "profile-ns-swe-backend",
            "target_section": "level_summary",
            "notes": "Profile level paragraph depends on the canonical L4 definition.",
        }
    )
    assert round_trip(profile) == profile
    assert round_trip(edge) == edge


def test_models_are_usable_without_fixtures_or_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    evidence = _evidence()
    assessment = RoleAssessment(
        role_id=evidence.role_id,
        proposed_family="engineering",
        proposed_track="individual_contributor",
        proposed_level="L4",
        confidence=0.88,
        fit_status=FitStatus.STRONG_FIT,
        supporting_evidence=["Service ownership and on-call"],
        counter_evidence=[],
        misfit_reasons=[],
    )
    assert assessment.proposed_family == "engineering"
