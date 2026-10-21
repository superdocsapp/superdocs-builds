from job_architecture.level import infer_level
from job_architecture.models import CareerTrackKind, RoleEvidence, SourceReference
from job_architecture.track import TrackInference, infer_track


def _manager_evidence(**overrides) -> RoleEvidence:
    payload = dict(
        role_id="synthetic-manager",
        title="Placeholder Title",
        organization="Example Co",
        team="Example",
        responsibilities=["Hire and coach a team of six engineers, including performance reviews."],
        scope="Accountable for one delivery team.",
        autonomy="Decide staffing and sequencing for that team.",
        complexity="Delivery of platform services.",
        impact="Team health and output.",
        leadership="Run weekly 1:1s.",
        people_management="This is a people-management role. You have direct reports. You hire, coach, and deliver performance ratings. You are the manager of record.",
        stakeholder_breadth="- Engineers on the team\n- Director of Engineering",
        domain_depth="Manage a software engineering team.",
        decision_making_authority="You decide who is on the team.",
        source_references=[SourceReference(document_id="synthetic-manager", locator="leadership and management")],
    )
    payload.update(overrides)
    return RoleEvidence(**payload)


def test_first_line_manager_is_m1_not_promoted() -> None:
    evidence = _manager_evidence()
    track = infer_track(evidence)
    assert track.track_id == "people_manager"
    level = infer_level(evidence, track)
    assert level.level_label == "M1"


def test_multi_team_manager_reaches_m2() -> None:
    evidence = _manager_evidence(
        role_id="synthetic-m2",
        responsibilities=[
            "Manage managers as direct reports and sequence staffing across those teams.",
            "Run skip-levels and calibration for multiple teams.",
        ],
        scope="Multiple teams within the function.",
        people_management="This is a people-management role. You have direct reports. You manage managers. Other managers report to you across several teams.",
        source_references=[SourceReference(document_id="synthetic-m2", locator="leadership and management")],
    )
    track = infer_track(evidence)
    assert track.kind is CareerTrackKind.PEOPLE_MANAGER
    assert infer_level(evidence, track).level_label == "M2"


def test_functional_leadership_reaches_m3() -> None:
    evidence = _manager_evidence(
        role_id="synthetic-m3",
        responsibilities=[
            "Set the leadership roster for the function and own org-wide people decisions.",
            "Lead managers-of-managers across the entire engineering organization.",
        ],
        scope="Function-wide organizational leadership.",
        people_management="This is a people-management role with functional leadership. You are accountable for managers-of-managers and the entire engineering organization.",
        source_references=[SourceReference(document_id="synthetic-m3", locator="leadership and management")],
    )
    assert infer_level(evidence, infer_track(evidence)).level_label == "M3"


def test_title_cannot_create_m2() -> None:
    evidence = _manager_evidence(title="Vice President of Engineering")
    assert infer_level(evidence, infer_track(evidence)).level_label == "M1"
