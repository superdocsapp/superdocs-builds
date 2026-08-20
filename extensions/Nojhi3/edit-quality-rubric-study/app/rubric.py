"""Rubric loading, validation, and score-sheet helpers."""

import json
from pathlib import Path
from typing import Any

from . import config

DIMENSION_IDS = [
    "faithfulness",
    "fact_accuracy",
    "content_preservation",
    "structural_integrity",
    "formatting_fidelity",
    "language_quality",
]


def load_rubric(path: Path = None) -> dict:
    path = path or config.RUBRIC_PATH
    rubric = json.loads(path.read_text(encoding="utf-8"))
    dims = [d["id"] for d in rubric["dimensions"]]
    if dims != DIMENSION_IDS:
        raise ValueError(f"unexpected dimension ids: {dims}")
    return rubric


def valid_score(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 4


def build_score_sheet(case_id: str, rater: str, scores: dict, evidence: dict = None) -> dict:
    rubric = load_rubric()
    out = {
        "case_id": case_id,
        "rater": rater,
        "scores": {},
        "evidence": {},
    }
    for dim in rubric["dimensions"]:
        did = dim["id"]
        score = scores.get(did)
        if not valid_score(score):
            raise ValueError(f"invalid score for {did}: {score!r}")
        out["scores"][did] = score
        out["evidence"][did] = (evidence or {}).get(did, "")
    return out