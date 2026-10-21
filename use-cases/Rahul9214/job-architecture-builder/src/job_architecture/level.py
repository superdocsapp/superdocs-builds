"""Canonical IC/M level inference from scope, autonomy, and related evidence."""

from __future__ import annotations

from dataclasses import dataclass

from job_architecture.catalog import (
    COMPILED_AUTONOMY_HIGH,
    COMPILED_AUTONOMY_LOW,
    COMPILED_COMPLEXITY_HIGH,
    COMPILED_COMPLEXITY_LOW,
    COMPILED_IMPACT_HIGH,
    COMPILED_IMPACT_LOW,
    COMPILED_LEADERSHIP_HIGH,
    COMPILED_LEADERSHIP_LOW,
    COMPILED_M2,
    COMPILED_M3,
    COMPILED_SCOPE_HIGH,
    COMPILED_SCOPE_LOW,
    COMPILED_SCOPE_MID,
    LEVEL_BY_LABEL,
    MANAGEMENT_M2_MIN,
    MANAGEMENT_M3_MIN,
)
from job_architecture.models import RoleEvidence
from job_architecture.scoring import Hit, score_text
from job_architecture.textutil import UNSTATED, parse_bullets
from job_architecture.track import TrackInference


@dataclass(frozen=True)
class LevelInference:
    level_label: str | None
    rank: int | None
    dimension_scores: dict[str, float]
    composite: float
    supporting: tuple[Hit, ...]
    counter: tuple[Hit, ...]


def _dimension_score(high: float, low: float, mid: float = 0.0) -> float:
    net = high + 0.55 * mid - low
    if net >= 1.6:
        return 4.0
    if net >= 0.9:
        return 3.0
    if net >= 0.25:
        return 2.0
    if low >= 0.9 and high < 0.4:
        return 1.0
    if net > 0:
        return 2.0
    if low > 0:
        return 1.0
    return 2.0


def _stakeholder_score(evidence: RoleEvidence) -> float:
    if evidence.stakeholder_breadth == UNSTATED:
        return 1.0
    n = len(parse_bullets(evidence.stakeholder_breadth))
    if n >= 6:
        return 4.0
    if n >= 4:
        return 3.0
    if n >= 2:
        return 2.0
    return 1.0


def _infer_management_level(evidence: RoleEvidence, track: TrackInference) -> LevelInference:
    text = " ".join(
        part
        for part in (
            evidence.people_management,
            evidence.leadership,
            evidence.scope,
            evidence.autonomy,
            *evidence.responsibilities,
            evidence.domain_depth if evidence.domain_depth != UNSTATED else "",
        )
        if part
    )
    m2_score, m2_hits = score_text(text, COMPILED_M2, lexicon="m2", honor_negation=True)
    m3_score, m3_hits = score_text(text, COMPILED_M3, lexicon="m3", honor_negation=True)
    if m3_score >= MANAGEMENT_M3_MIN and m3_score >= m2_score:
        label = "M3"
        supporting = m3_hits
    elif m2_score >= MANAGEMENT_M2_MIN:
        label = "M2"
        supporting = m2_hits
    else:
        label = "M1"
        supporting = track.supporting
    return LevelInference(
        level_label=label,
        rank=LEVEL_BY_LABEL[label].rank,
        dimension_scores={"people_management": 4.0, "m2": m2_score, "m3": m3_score},
        composite=4.0 if label == "M1" else 5.0 if label == "M2" else 6.0,
        supporting=tuple(supporting),
        counter=track.counter,
    )


def infer_level(evidence: RoleEvidence, track: TrackInference) -> LevelInference:
    if track.track_id == "people_manager":
        return _infer_management_level(evidence, track)

    text = " ".join(
        part
        for part in (
            *evidence.responsibilities,
            evidence.scope,
            evidence.autonomy,
            evidence.complexity if evidence.complexity != UNSTATED else "",
            evidence.impact if evidence.impact != UNSTATED else "",
            evidence.leadership if evidence.leadership != UNSTATED else "",
            evidence.decision_making_authority,
            evidence.domain_depth if evidence.domain_depth != UNSTATED else "",
        )
        if part
    )
    supporting: list[Hit] = []
    counter: list[Hit] = []

    def collect(compiled, lexicon: str, *, honor_negation: bool = True) -> float:
        score, hits = score_text(text, compiled, lexicon=lexicon, honor_negation=honor_negation)
        for hit in hits:
            if hit.weight >= 0:
                supporting.append(hit)
            else:
                counter.append(hit)
        return score

    scope_high = collect(COMPILED_SCOPE_HIGH, "scope_high")
    scope_mid = collect(COMPILED_SCOPE_MID, "scope_mid")
    scope_low = collect(COMPILED_SCOPE_LOW, "scope_low", honor_negation=False)
    autonomy_high = collect(COMPILED_AUTONOMY_HIGH, "autonomy_high")
    autonomy_low = collect(COMPILED_AUTONOMY_LOW, "autonomy_low", honor_negation=False)
    complexity_high = collect(COMPILED_COMPLEXITY_HIGH, "complexity_high")
    complexity_low = collect(COMPILED_COMPLEXITY_LOW, "complexity_low", honor_negation=False)
    impact_high = collect(COMPILED_IMPACT_HIGH, "impact_high")
    impact_low = collect(COMPILED_IMPACT_LOW, "impact_low", honor_negation=False)
    leadership_high = collect(COMPILED_LEADERSHIP_HIGH, "leadership_high")
    leadership_low = collect(COMPILED_LEADERSHIP_LOW, "leadership_low", honor_negation=False)

    dimensions = {
        "scope": _dimension_score(scope_high, scope_low, scope_mid),
        "autonomy": _dimension_score(autonomy_high, autonomy_low),
        "complexity": _dimension_score(complexity_high, complexity_low),
        "impact": _dimension_score(impact_high, impact_low),
        "leadership": _dimension_score(leadership_high, leadership_low),
        "stakeholders": _stakeholder_score(evidence),
    }
    if evidence.decision_making_authority:
        if any(token in evidence.decision_making_authority.lower() for token in ("default decision", "sign-off", "freeze", "block a release")):
            dimensions["decision"] = 4.0
        elif "cannot" in evidence.decision_making_authority.lower() or "already" in evidence.autonomy.lower():
            dimensions["decision"] = 2.0 if "cannot" in evidence.decision_making_authority.lower() else 1.0
        else:
            dimensions["decision"] = 3.0
    else:
        dimensions["decision"] = dimensions["autonomy"]

    weights = {
        "scope": 1.3,
        "autonomy": 1.2,
        "complexity": 1.0,
        "impact": 1.2,
        "leadership": 0.9,
        "stakeholders": 0.6,
        "decision": 1.0,
    }
    composite = sum(dimensions[key] * weights[key] for key in weights) / sum(weights.values())

    # Thin, locally scoped work should not float to mid-level because of missing high signals.
    if dimensions["scope"] <= 1.0 and dimensions["autonomy"] <= 1.0:
        composite = min(composite, 1.35)

    if composite < 1.45:
        label = "IC1"
    elif composite < 2.05:
        label = "IC2"
    elif composite < 2.7:
        label = "IC3"
    elif composite < 3.35:
        label = "IC4"
    else:
        label = "IC5"

    return LevelInference(
        level_label=label,
        rank=LEVEL_BY_LABEL[label].rank,
        dimension_scores=dimensions,
        composite=round(composite, 4),
        supporting=tuple(supporting),
        counter=tuple(counter),
    )
