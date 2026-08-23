"""Confidence calibration via dual-extraction agreement.

SuperDocs' `field_confidence` numbers are the model's own self-reported
confidence -- there is no guarantee "0.9" means "90% likely to be
correct" in any calibrated sense; it just means "the model said 0.9."
This module gives the extract stage a second, independent signal: run
extraction twice with differently-phrased instructions and compare the
two results field by field. Agreement between two independent runs is
evidence of correctness in a way a single self-reported number isn't;
disagreement is a strong signal the field is genuinely uncertain
regardless of what either run's own confidence said.

This is opt-in (BoxMetadataWritebackPipeline(..., enable_calibration=True))
rather than the default, because it doubles the extract stage's SuperDocs
operations (and therefore cost and latency) for every file -- a tenant
trades cost for a materially more trustworthy confidence signal on
fields that drive retention decisions, which the round-2 writeup itself
lists as a real trade-off worth making optional rather than forced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Field-type-aware normalization before comparing two runs' values --
# "2026-01-15" and "01/15/2026" should agree, and "$84,000.00" and
# "84000" should agree, since these are genuinely the same extracted
# fact expressed differently by two independently-phrased prompts, not
# a real disagreement.
_MONEY_CHARS = str.maketrans("", "", "$,")


def _normalize_for_comparison(field_name: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if field_name == "contract_value":
        v = v.translate(_MONEY_CHARS).strip()
        try:
            return str(float(v))
        except ValueError:
            return v.lower()
    if field_name in ("effective_date", "expiration_date"):
        # Accept both ISO (2026-01-15) and US slash (01/15/2026) without
        # pulling in a date-parsing dependency for this narrow case.
        parts = v.replace("/", "-").split("-")
        if len(parts) == 3 and len(parts[2]) == 4:  # MM-DD-YYYY -> YYYY-MM-DD
            parts = [parts[2], parts[0], parts[1]]
        return "-".join(p.zfill(2) if p.isdigit() and len(p) < 4 else p for p in parts)
    return v.lower()


@dataclass
class CalibratedField:
    field_name: str
    first_value: Optional[str]
    second_value: Optional[str]
    agreed: bool
    self_reported_confidence: float
    calibrated_confidence: float


# Two independent runs agreeing is stronger evidence than either run's
# own self-reported number, so agreement pulls confidence UP toward 1.0
# (capped) and disagreement pulls it firmly DOWN -- a disagreement means
# the field should very likely be queued for human review regardless of
# what either run claimed about itself.
_AGREEMENT_BONUS = 0.15
_DISAGREEMENT_CEILING = 0.4


def calibrate_fields(
    first_fields: dict[str, Optional[str]],
    first_confidences: dict[str, float],
    second_fields: dict[str, Optional[str]],
) -> dict[str, CalibratedField]:
    """Compares two independent extraction runs field by field and
    returns a calibrated confidence per field. Only fields present in
    `first_fields` are calibrated (the first run is the one whose
    values actually get written; the second run exists purely to
    validate it)."""
    results: dict[str, CalibratedField] = {}
    for field_name, first_value in first_fields.items():
        second_value = second_fields.get(field_name)
        self_reported = first_confidences.get(field_name, 1.0)
        agreed = _normalize_for_comparison(field_name, first_value) == _normalize_for_comparison(
            field_name, second_value
        )
        if agreed and first_value is not None:
            calibrated = min(1.0, self_reported + _AGREEMENT_BONUS)
        else:
            calibrated = min(self_reported, _DISAGREEMENT_CEILING)
        results[field_name] = CalibratedField(
            field_name=field_name,
            first_value=first_value,
            second_value=second_value,
            agreed=agreed,
            self_reported_confidence=self_reported,
            calibrated_confidence=calibrated,
        )
    return results


@dataclass
class EnsembleCalibratedField:
    field_name: str
    canonical_value: Optional[str]  # the majority-vote (or first, on a tie) value
    self_reported_confidence: float
    calibrated_confidence: float
    agreement_fraction: float  # fraction of runs whose (normalized) value matched the canonical one
    run_count: int


def calibrate_fields_ensemble(
    primary_fields: dict[str, Optional[str]],
    primary_confidences: dict[str, float],
    additional_runs: list[dict[str, Optional[str]]],
) -> dict[str, EnsembleCalibratedField]:
    """N-way extension of calibrate_fields: instead of one second
    opinion, takes any number of additional independent extraction
    runs and uses the DISTRIBUTION of answers as the confidence signal,
    not just a binary match/mismatch. "4 of 5 runs agree" is more
    precise evidence than "2 of 2 agree" -- it distinguishes a field
    the model is robustly confident about from one where a second run
    happened to land on the same (possibly still wrong) answer by
    chance.

    The canonical (written) value is always taken from primary_fields,
    same principle as calibrate_fields: additional runs are validation
    signal only, never a value source themselves -- this keeps
    provenance simple (the value always traces back to one real
    SuperDocs session, see pipeline.py's field_session_ids) rather than
    a value potentially assembled from whichever run happened to "win"
    a vote.

    Confidence scales with agreement_fraction: unanimous agreement
    across all runs earns the full _AGREEMENT_BONUS; partial agreement
    earns a proportionally smaller bonus; agreement_fraction at or
    below 0.5 (no clear majority) is treated as a disagreement, same
    ceiling as the pairwise case."""
    results: dict[str, EnsembleCalibratedField] = {}
    for field_name, primary_value in primary_fields.items():
        self_reported = primary_confidences.get(field_name, 1.0)
        normalized_primary = _normalize_for_comparison(field_name, primary_value)
        run_values = [primary_value] + [run.get(field_name) for run in additional_runs]
        run_count = len(run_values)
        matches = sum(
            1 for v in run_values if _normalize_for_comparison(field_name, v) == normalized_primary
        )
        agreement_fraction = matches / run_count if run_count else 0.0

        if agreement_fraction > 0.5 and primary_value is not None:
            # Scale the bonus by how unanimous the ensemble was --
            # 5-of-5 earns the full bonus, 3-of-5 earns 60% of it.
            calibrated = min(1.0, self_reported + _AGREEMENT_BONUS * agreement_fraction)
        else:
            calibrated = min(self_reported, _DISAGREEMENT_CEILING)

        results[field_name] = EnsembleCalibratedField(
            field_name=field_name,
            canonical_value=primary_value,
            self_reported_confidence=self_reported,
            calibrated_confidence=calibrated,
            agreement_fraction=agreement_fraction,
            run_count=run_count,
        )
    return results
