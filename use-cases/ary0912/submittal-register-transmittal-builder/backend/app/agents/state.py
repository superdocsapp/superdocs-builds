from typing import Any, TypedDict


class SubmittalState(TypedDict, total=False):

    # --------------------------------------------------------
    # Identifiers
    # --------------------------------------------------------

    project_id: str
    submittal_id: str
    specification_section: str
    scenario: str

    # --------------------------------------------------------
    # Documents
    # --------------------------------------------------------

    specification: dict
    submission: dict

    # --------------------------------------------------------
    # AI comparison findings
    # --------------------------------------------------------

    findings: list[dict]

    # --------------------------------------------------------
    # Human review
    # --------------------------------------------------------

    review_status: str
    human_review: dict[str, Any]

    # --------------------------------------------------------
    # Downstream workflow
    # --------------------------------------------------------

    transmittal_id: str
    current_stage: str

    # --------------------------------------------------------
    # Telemetry & Cost Reporting
    # --------------------------------------------------------

    stage_durations: dict[str, float]
    operations_count: int
    error: str | None

    # --------------------------------------------------------
    # Workflow control
    # --------------------------------------------------------

    retry_count: int
    escalated: bool
    skipped_review: bool
