"""Load a DraftRequest from a YAML input file. See examples/sample_input.yaml
for the shape."""
from __future__ import annotations

import yaml

from .models import ActionItem, DraftRequest, EightDInputs, FailureMode, PPAPInputs


def load_draft_request(path: str) -> DraftRequest:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    failure_modes = [
        FailureMode(
            id=fm["id"],
            function=fm["function"],
            failure_mode=fm["failure_mode"],
            effect=fm["effect"],
            severity=fm.get("severity"),
            occurrence=fm.get("occurrence"),
            detection=fm.get("detection"),
            current_controls=fm.get("current_controls", ""),
        )
        for fm in data.get("failure_modes", [])
    ]

    actions = [
        ActionItem(
            id=a["id"],
            failure_mode_id=a["failure_mode_id"],
            recommended_action=a["recommended_action"],
            responsible=a.get("responsible"),
            target_date=a.get("target_date"),
            status=a.get("status", "open"),
        )
        for a in data.get("actions", [])
    ]

    ppap_data = data.get("ppap")
    ppap = PPAPInputs(**ppap_data) if ppap_data else None

    eightd_data = data.get("eightd")
    eightd = EightDInputs(**eightd_data) if eightd_data else None

    return DraftRequest(
        document_type=data["document_type"],
        item_or_process=data["item_or_process"],
        customer_name=data["customer_name"],
        engineer_name=data["engineer_name"],
        failure_modes=failure_modes,
        actions=actions,
        ppap=ppap,
        eightd=eightd,
    )
