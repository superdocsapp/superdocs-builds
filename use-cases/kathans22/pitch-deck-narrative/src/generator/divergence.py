"""Pairwise lexical-overlap scoring for narrative section texts.

Measurement first, generation second — zero SuperDocs operations. Arithmetic only.
This module is Build 2's counterpart to Build 1's core-hash: a number a reviewer can
check instead of a substance claim they have to take on trust.

------------------------------------------------------------------------------
Divergence thresholds — what \"low enough\" means
------------------------------------------------------------------------------

Metric: word-level Jaccard on normalised tokens (see ``score_pair``).

**Vertical-tagged sections** (Problem, Why Now, Solution Fit, Proof, Objection, ROI)
must differ in substance. Empirically, on hand-made fixtures in this repo:

- A genuine legal-vs-fintech objection pair scores ~0.03.
- The same objection with industry nouns swapped scores ~0.70.
- Identical shared Opening copy scores 1.0 (expected — product is held constant).

So:

- ``VERTICAL_MEAN_MAX = 0.40`` — mean Jaccard across all pair×vertical-section cells
  must stay **below 0.40**. That sits between the genuine band (~0.05–0.25 with some
  shared product vocabulary like \"ClarityDocs\" / \"approve\") and the template-and-swap
  band (~0.60+). Below 0.40 is \"low enough\" for this build.
- ``VERTICAL_SECTION_MAX = 0.55`` — **any single** vertical-tagged section pair at or
  above 0.55 is a template-and-swap failure even if other sections pull the mean down.
  Objection and Proof are where swaps hide; one hot section is enough to fail.

**Shared-tagged sections** (Opening, Product Overview, Call to Action) may score
higher — the product is constant by design. They are reported for visibility but do
**not** fail the run on high overlap.

**Template-and-swap failure** = ``mean_vertical_overlap >= VERTICAL_MEAN_MAX`` OR any
vertical-tagged section pair ``>= VERTICAL_SECTION_MAX``. Do not loosen these numbers
to pass weak packs — fix the knowledge files / narratives instead.
"""

from __future__ import annotations

import json
import re
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any, Mapping

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")

SectionKey = int | str
Narratives = Mapping[str, Mapping[SectionKey, str]]
SectionWeights = Mapping[SectionKey, str]

# See module docstring for justification. Do not raise these to make weak packs pass.
VERTICAL_MEAN_MAX = 0.40
VERTICAL_SECTION_MAX = 0.55


def normalize_tokens(text: str) -> frozenset[str]:
    """Lowercase alphanumeric tokens; punctuation stripped. No stemming, no stopword list."""
    if not text:
        return frozenset()
    return frozenset(_TOKEN_RE.findall(text.lower()))


def score_pair(text_a: str, text_b: str) -> float:
    """Return word-level Jaccard similarity between two section texts.

    Why Jaccard (not embeddings / cosine over TF-IDF):
    - Dependency-light — stdlib only; no model call and no ops cost.
    - Interpretable — |A∩B| / |A∪B| is a number a reviewer can recompute by hand.
    - Sensitive to template-and-swap — noun-swapped scripts share most function and
      structure words, so the union barely grows while the intersection stays large;
      genuinely different objections and proof points shrink the intersection.

    Returns 0.0 when both sides are empty (no signal). Returns 0.0 when only one side
    has tokens (no shared vocabulary to claim overlap). Otherwise a float in [0.0, 1.0].
    """
    tokens_a = normalize_tokens(text_a)
    tokens_b = normalize_tokens(text_b)
    if not tokens_a and not tokens_b:
        return 0.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _section_keys(narratives: Narratives) -> list[SectionKey]:
    keys: set[SectionKey] = set()
    for sections in narratives.values():
        keys.update(sections.keys())
    return sorted(keys, key=lambda k: (str(type(k)), k))


def _weight_for(section: SectionKey, section_weights: SectionWeights) -> str | None:
    if section in section_weights:
        return section_weights[section]
    if isinstance(section, str) and section.isdigit():
        as_int = int(section)
        if as_int in section_weights:
            return section_weights[as_int]
    if not isinstance(section, str):
        as_str = str(section)
        if as_str in section_weights:
            return section_weights[as_str]  # type: ignore[index]
    return None


def score_all(
    narratives: Narratives,
    section_weights: SectionWeights,
) -> dict[str, Any]:
    """Score every vertical pair on every section; aggregate means by weight tag.

    Parameters
    ----------
    narratives:
        ``{vertical_name: {section_key: section_text}}``. Section keys must align
        with ``section_weights`` (typically section numbers from the deck manifest).
    section_weights:
        ``{section_key: \"shared\" | \"vertical\"}`` from the deck manifest.

    Returns
    -------
    report dict with:
      - ``pairs``: list of {vertical_a, vertical_b, sections: {section: score}}
      - ``aggregates``: mean overlap across all pair×section cells tagged
        ``vertical`` vs ``shared``
      - ``per_pair_aggregates``: same means broken out per vertical pair
    """
    verticals = sorted(narratives.keys())
    if len(verticals) < 2:
        raise ValueError("score_all requires at least two verticals")

    unknown = set(section_weights.values()) - {"shared", "vertical"}
    if unknown:
        raise ValueError(f"section_weights values must be shared|vertical, got {unknown}")

    sections = _section_keys(narratives)
    pairs: list[dict[str, Any]] = []
    vertical_scores: list[float] = []
    shared_scores: list[float] = []
    per_pair_aggregates: list[dict[str, Any]] = []

    for va, vb in combinations(verticals, 2):
        section_scores: dict[str, float] = {}
        pair_vertical: list[float] = []
        pair_shared: list[float] = []
        for section in sections:
            text_a = narratives[va].get(section, "")
            text_b = narratives[vb].get(section, "")
            score = score_pair(text_a, text_b)
            section_scores[str(section)] = score

            weight = _weight_for(section, section_weights)
            if weight == "vertical":
                vertical_scores.append(score)
                pair_vertical.append(score)
            elif weight == "shared":
                shared_scores.append(score)
                pair_shared.append(score)
            else:
                raise ValueError(
                    f"missing weight for section {section!r}; "
                    f"every scored section must be tagged shared|vertical"
                )

        pairs.append(
            {
                "vertical_a": va,
                "vertical_b": vb,
                "sections": section_scores,
            }
        )
        per_pair_aggregates.append(
            {
                "vertical_a": va,
                "vertical_b": vb,
                "mean_vertical_overlap": mean(pair_vertical) if pair_vertical else None,
                "mean_shared_overlap": mean(pair_shared) if pair_shared else None,
            }
        )

    return {
        "method": "word_jaccard",
        "verticals": verticals,
        "pairs": pairs,
        "aggregates": {
            "mean_vertical_overlap": mean(vertical_scores) if vertical_scores else None,
            "mean_shared_overlap": mean(shared_scores) if shared_scores else None,
            "vertical_cells": len(vertical_scores),
            "shared_cells": len(shared_scores),
        },
        "per_pair_aggregates": per_pair_aggregates,
        "thresholds": {
            "vertical_mean_max": VERTICAL_MEAN_MAX,
            "vertical_section_max": VERTICAL_SECTION_MAX,
            "shared_sections_gated": False,
        },
    }


def evaluate_divergence(
    report: Mapping[str, Any],
    section_weights: SectionWeights,
) -> dict[str, Any]:
    """Apply the documented thresholds to a ``score_all`` report.

    Passes only when mean vertical overlap is below ``VERTICAL_MEAN_MAX`` and every
    vertical-tagged section pair is below ``VERTICAL_SECTION_MAX``. Shared overlap
    is recorded but never fails the gate.
    """
    mean_vertical = report.get("aggregates", {}).get("mean_vertical_overlap")
    failures: list[str] = []

    if mean_vertical is None:
        failures.append("no vertical-tagged section scores present")
    elif mean_vertical >= VERTICAL_MEAN_MAX:
        failures.append(
            f"mean_vertical_overlap {mean_vertical:.3f} >= {VERTICAL_MEAN_MAX} "
            f"(template-and-swap / weak substance)"
        )

    vertical_section_ids = {
        str(section) for section, weight in section_weights.items() if weight == "vertical"
    }

    hot_sections: list[dict[str, Any]] = []
    for pair in report.get("pairs", []):
        for section, score in pair.get("sections", {}).items():
            if section not in vertical_section_ids:
                continue
            if score >= VERTICAL_SECTION_MAX:
                hot = {
                    "vertical_a": pair["vertical_a"],
                    "vertical_b": pair["vertical_b"],
                    "section": section,
                    "score": score,
                }
                hot_sections.append(hot)
                failures.append(
                    f"section {section} {pair['vertical_a']}↔{pair['vertical_b']} "
                    f"overlap {score:.3f} >= {VERTICAL_SECTION_MAX}"
                )

    return {
        "passed": not failures,
        "failures": failures,
        "hot_sections": hot_sections,
        "mean_vertical_overlap": mean_vertical,
        "mean_shared_overlap": report.get("aggregates", {}).get("mean_shared_overlap"),
        "thresholds": {
            "vertical_mean_max": VERTICAL_MEAN_MAX,
            "vertical_section_max": VERTICAL_SECTION_MAX,
            "shared_sections_gated": False,
        },
    }


def coverage_notes(
    narratives: Narratives,
    expected_sections: list[SectionKey],
) -> list[dict[str, Any]]:
    """Flag verticals missing a section body (parser miss or unfilled heading)."""
    notes: list[dict[str, Any]] = []
    for vertical, sections in sorted(narratives.items()):
        present = set(sections.keys()) | {str(k) for k in sections.keys()}
        for section in expected_sections:
            keys = {section, str(section)}
            if isinstance(section, str) and section.isdigit():
                keys.add(int(section))
            body = ""
            for key in keys:
                if key in sections:
                    body = sections[key] or ""
                    break
            if not str(body).strip():
                notes.append(
                    {
                        "vertical": vertical,
                        "section": str(section),
                        "issue": "missing_or_empty_section_body",
                        "detail": (
                            "No parseable Slide-equivalent body for this section. "
                            "Often caused by a nonstandard heading (not "
                            "'## Slide-equivalent N — …'). Rework before trusting "
                            "this cell's overlap score."
                        ),
                    }
                )
    return notes


def highest_vertical_cells(
    report: Mapping[str, Any],
    section_weights: SectionWeights,
    *,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Largest vertical-tagged pair×section scores — never hide a hot cell in the mean."""
    vertical_ids = {
        str(section) for section, weight in section_weights.items() if weight == "vertical"
    }
    cells: list[dict[str, Any]] = []
    for pair in report.get("pairs", []):
        for section, score in pair.get("sections", {}).items():
            if section not in vertical_ids:
                continue
            cells.append(
                {
                    "section": section,
                    "vertical_a": pair["vertical_a"],
                    "vertical_b": pair["vertical_b"],
                    "score": score,
                    "at_or_above_section_max": score >= VERTICAL_SECTION_MAX,
                }
            )
    cells.sort(key=lambda c: c["score"], reverse=True)
    return cells[:limit]


def write_divergence_report(
    narratives: Narratives,
    section_weights: SectionWeights,
    *,
    dest: Path,
    manifest_version: int | None = None,
) -> dict[str, Any]:
    """Run ``score_all`` + ``evaluate_divergence`` and write evidence JSON (0 ops)."""
    if len(narratives) < 2:
        raise ValueError("write_divergence_report requires at least two verticals")

    report = score_all(narratives, section_weights)
    evaluation = evaluate_divergence(report, section_weights)
    expected = sorted(section_weights.keys(), key=lambda k: (str(type(k)), k))
    notes = coverage_notes(narratives, expected)
    top_vertical = highest_vertical_cells(report, section_weights)

    payload: dict[str, Any] = {
        "status": "scored",
        "manifest_version": manifest_version,
        "verticals": sorted(narratives.keys()),
        "section_weights": {str(k): v for k, v in sorted(section_weights.items(), key=lambda kv: (str(type(kv[0])), kv[0]))},
        "thresholds": {
            "vertical_mean_max": VERTICAL_MEAN_MAX,
            "vertical_section_max": VERTICAL_SECTION_MAX,
            "shared_sections_gated": False,
        },
        "report": report,
        "evaluation": evaluation,
        "highest_vertical_cells": top_vertical,
        "coverage_notes": notes,
        "verdict": "PASS" if evaluation["passed"] else "FAIL",
    }
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["report_path"] = str(dest)
    return payload
