"""Structured input types for the FMEA / PPAP / 8D drafter.

Nothing in this module talks to the network. It exists so `validate.py` has
typed data to check and `render.py` has typed data to render — the engineer's
numbers pass through unchanged from here to the final document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FailureMode:
    id: str  # short stable id, e.g. "FM-01" — action rows reference this
    function: str
    failure_mode: str
    effect: str
    severity: Optional[int] = None  # 1-10, AIAG-VDA scale
    occurrence: Optional[int] = None  # 1-10
    detection: Optional[int] = None  # 1-10
    current_controls: str = ""

    def missing_fields(self) -> list[str]:
        missing = []
        if self.severity is None:
            missing.append("severity")
        if self.occurrence is None:
            missing.append("occurrence")
        if self.detection is None:
            missing.append("detection")
        return missing

    def rpn(self) -> Optional[int]:
        if self.severity is None or self.occurrence is None or self.detection is None:
            return None
        return self.severity * self.occurrence * self.detection


@dataclass
class ActionItem:
    id: str
    failure_mode_id: str  # must match a FailureMode.id — enforced in validate.py
    recommended_action: str
    responsible: Optional[str] = None
    target_date: Optional[str] = None
    status: str = "open"


@dataclass
class PPAPInputs:
    """Narrative sections of a PPAP submission (Production Part Approval Process)."""
    part_number: str
    part_name: str
    supplier_name: str
    customer_name: str
    submission_level: Optional[int] = None  # 1-5, AIAG PPAP levels
    reason_for_submission: str = ""
    design_records_summary: str = ""
    process_flow_summary: str = ""
    control_plan_summary: str = ""
    dimensional_results_summary: str = ""
    material_performance_summary: str = ""


@dataclass
class EightDInputs:
    """8D problem-solving report sections (D1-D8)."""
    d1_team: str = ""
    d2_problem_description: str = ""
    d3_containment_actions: str = ""
    d4_root_cause: str = ""
    d5_permanent_corrective_actions: str = ""
    d6_implementation_verification: str = ""
    d7_prevent_recurrence: str = ""
    d8_team_recognition: str = ""


@dataclass
class DraftRequest:
    """Everything needed to draft one supplier-quality package for one customer."""
    document_type: str  # "fmea" | "ppap" | "8d" | "combined"
    item_or_process: str
    customer_name: str
    engineer_name: str
    failure_modes: list[FailureMode] = field(default_factory=list)
    actions: list[ActionItem] = field(default_factory=list)
    ppap: Optional[PPAPInputs] = None
    eightd: Optional[EightDInputs] = None
