"""Career-track inference from people-management evidence, not job titles."""

from __future__ import annotations

from dataclasses import dataclass

from job_architecture.catalog import COMPILED_PM_NEGATIVE, COMPILED_PM_POSITIVE, TRACK_MANAGER_MIN
from job_architecture.models import CareerTrackKind, RoleEvidence
from job_architecture.scoring import Hit, score_text


@dataclass(frozen=True)
class TrackInference:
    track_id: str | None
    kind: CareerTrackKind | None
    manager_score: float
    ic_score: float
    supporting: tuple[Hit, ...]
    counter: tuple[Hit, ...]
    decisive: bool


def infer_track(evidence: RoleEvidence) -> TrackInference:
    text = " ".join(
        part
        for part in (
            evidence.people_management,
            evidence.leadership,
            *evidence.responsibilities,
            evidence.scope,
            evidence.autonomy,
        )
        if part
    )
    positive, pos_hits = score_text(text, COMPILED_PM_POSITIVE, lexicon="people_manager")
    negative, neg_hits = score_text(
        text,
        COMPILED_PM_NEGATIVE,
        lexicon="individual_contributor",
        honor_negation=False,
    )
    # Negative lexicon already encodes absence of management; do not flip those hits.
    manager_net = positive - negative
    supporting: list[Hit] = []
    counter: list[Hit] = []
    if manager_net >= TRACK_MANAGER_MIN:
        track_id = "people_manager"
        kind = CareerTrackKind.PEOPLE_MANAGER
        supporting.extend(pos_hits)
        counter.extend(neg_hits)
        decisive = True
    elif negative > positive:
        track_id = "individual_contributor"
        kind = CareerTrackKind.INDIVIDUAL_CONTRIBUTOR
        supporting.extend(neg_hits)
        counter.extend(pos_hits)
        decisive = negative >= 1.5
    else:
        track_id = "individual_contributor"
        kind = CareerTrackKind.INDIVIDUAL_CONTRIBUTOR
        supporting.extend(neg_hits)
        counter.extend(pos_hits)
        decisive = False

    return TrackInference(
        track_id=track_id,
        kind=kind,
        manager_score=round(manager_net, 4),
        ic_score=round(negative, 4),
        supporting=tuple(supporting),
        counter=tuple(counter),
        decisive=decisive,
    )
