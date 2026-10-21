"""Family inference from responsibilities and domain evidence, not titles."""

from __future__ import annotations

from dataclasses import dataclass

from job_architecture.catalog import (
    COMPILED_FAMILY_LEXICONS,
    COMPILED_OUTSIDE,
    COMPILED_SALES_RIVAL,
    FAMILY_ASSIGN_MIN,
    FAMILY_HYBRID_ABS,
    FAMILY_HYBRID_RATIO,
    OUTSIDE_ASSIGN_MIN,
)
from job_architecture.evidence import scoring_text
from job_architecture.models import RoleEvidence
from job_architecture.scoring import Hit, score_text


@dataclass(frozen=True)
class FamilyInference:
    family_id: str | None
    scores: dict[str, float]
    supporting: tuple[Hit, ...]
    counter: tuple[Hit, ...]
    rival_ids: tuple[str, ...]
    outside_score: float
    is_hybrid: bool
    is_outside: bool


def infer_family(evidence: RoleEvidence) -> FamilyInference:
    return infer_family_from_text(scoring_text(evidence))


def infer_family_from_text(text: str) -> FamilyInference:
    scores: dict[str, float] = {}
    supporting: list[Hit] = []
    counter: list[Hit] = []
    for family_id, compiled in COMPILED_FAMILY_LEXICONS.items():
        score, hits = score_text(text, compiled, lexicon=family_id)
        scores[family_id] = score
        for hit in hits:
            if hit.weight >= 0:
                supporting.append(hit)
            else:
                counter.append(hit)

    sales_score, sales_hits = score_text(text, COMPILED_SALES_RIVAL, lexicon="sales")
    scores["_sales"] = sales_score
    for hit in sales_hits:
        (supporting if hit.weight >= 0 else counter).append(hit)

    outside_score, outside_hits = score_text(text, COMPILED_OUTSIDE, lexicon="outside_architecture")
    for hit in outside_hits:
        (supporting if hit.weight >= 0 else counter).append(hit)

    real_scores = {key: value for key, value in scores.items() if not key.startswith("_")}
    ranked = sorted(real_scores.items(), key=lambda item: item[1], reverse=True)
    top_id, top_score = ranked[0]
    second_id, second_score = ranked[1]
    rival_ids: list[str] = []

    is_outside = outside_score >= OUTSIDE_ASSIGN_MIN and outside_score >= top_score - 0.5

    contenders: list[tuple[str, float]] = [
        (family_id, score) for family_id, score in ranked if score >= FAMILY_HYBRID_ABS
    ]
    if sales_score >= FAMILY_HYBRID_ABS:
        contenders.append(("sales", sales_score))
    contenders.sort(key=lambda item: item[1], reverse=True)

    sales_with_family = sales_score >= FAMILY_HYBRID_ABS and top_score >= FAMILY_ASSIGN_MIN
    close_families = (
        second_score >= FAMILY_HYBRID_ABS and second_score >= top_score * FAMILY_HYBRID_RATIO
    )
    is_hybrid = sales_with_family or close_families
    if is_hybrid:
        rival_ids.extend(item[0] for item in contenders[:3])

    family_id: str | None = None
    if is_outside:
        family_id = None
    elif is_hybrid:
        family_id = None
    elif top_score >= FAMILY_ASSIGN_MIN:
        family_id = top_id
        if second_score >= top_score * FAMILY_HYBRID_RATIO and second_score >= 1.5:
            rival_ids.append(second_id)
    else:
        family_id = None

    return FamilyInference(
        family_id=family_id,
        scores=scores,
        supporting=tuple(supporting),
        counter=tuple(counter),
        rival_ids=tuple(dict.fromkeys(rival_ids)),
        outside_score=outside_score,
        is_hybrid=is_hybrid,
        is_outside=is_outside,
    )
