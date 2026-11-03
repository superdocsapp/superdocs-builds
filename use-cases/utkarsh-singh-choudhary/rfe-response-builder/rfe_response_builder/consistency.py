"""
Cross-item consistency checking.

`grounding.py` catches a single section inventing a detail that isn't in
ITS OWN source material. It cannot catch a distinct, equally real failure
mode: two DIFFERENT sections, drafted independently (one `chat` turn per
RFE item -- see generate.py/review.py), stating CONTRADICTORY facts about
the same underlying thing -- e.g. item 3's response says the beneficiary
worked at "Acme Robotics Corp" from 2018-2022, and item 5's response
(drafted in a separate turn, with no visibility into what item 3 said)
says 2019-2023. Nothing before this module checked for that.

This is a heuristic, not a knowledge-graph or entity-resolution system:
it finds proper-noun-shaped phrases (reusing `grounding.py`'s extractors)
that appear in more than one drafted section, and if the SAME phrase
co-occurs with different numeric "checkable facts" (years, durations,
money amounts) across those sections, flags it as worth a human's
attention. Like every other heuristic signal in this package
(`fuzzy_matches`, `semantic_matches`, `ungrounded_facts`,
`QualityVerdict`), a flag here is never auto-corrected or blocked --
it's purely something for the reviewer to double-check, and it can have
false positives (two sections legitimately discussing different aspects
of the same company at different points in the applicant's career) as
well as false negatives (a genuine contradiction that doesn't happen to
share a detectable proper noun).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from .grounding import _extract_numeric_facts, _extract_proper_nouns, _normalize


@dataclass
class ConsistencyFlag:
    request_id_a: str
    request_id_b: str
    shared_entity: str
    facts_a: list[str]
    facts_b: list[str]


def check_cross_item_consistency(items: list[tuple[str, str]]) -> list[ConsistencyFlag]:
    """`items` is a list of (request_id, drafted_reply_text) pairs -- one
    per RFE item that actually has drafted text (callers should exclude
    failed/not-answered items before calling this). Returns a list of
    `ConsistencyFlag`, one per (item pair, shared entity) combination
    where the numeric facts near that entity differ between the two
    items. Empty list if nothing looks contradictory, which is the
    common case and NOT itself evidence that everything is consistent --
    this only catches contradictions involving a shared proper-noun-shaped
    phrase and a differing checkable numeric fact."""
    # Pre-extract once per item rather than recomputing inside the O(n^2)
    # pair loop below.
    entities_by_item = {rid: _extract_proper_nouns(text) for rid, text in items}
    facts_by_item = {rid: _extract_numeric_facts(text) for rid, text in items}

    flags: list[ConsistencyFlag] = []
    for (rid_a, _), (rid_b, _) in combinations(items, 2):
        shared_entities = entities_by_item[rid_a] & entities_by_item[rid_b]
        if not shared_entities:
            continue
        facts_a, facts_b = facts_by_item[rid_a], facts_by_item[rid_b]
        # Only compare facts that are present in BOTH items -- a fact
        # that appears in one item and simply isn't mentioned in the
        # other isn't a contradiction, it's just not discussed there.
        normalized_a = {_normalize(f) for f in facts_a}
        normalized_b = {_normalize(f) for f in facts_b}
        if not normalized_a or not normalized_b:
            continue
        if normalized_a == normalized_b:
            continue
        # There's at least one fact unique to each side -- with a shared
        # entity, that's the specific pattern this check exists for.
        unique_to_a = normalized_a - normalized_b
        unique_to_b = normalized_b - normalized_a
        if unique_to_a and unique_to_b:
            for entity in sorted(shared_entities):
                flags.append(ConsistencyFlag(
                    request_id_a=rid_a, request_id_b=rid_b, shared_entity=entity,
                    facts_a=sorted(f for f in facts_a if _normalize(f) in unique_to_a),
                    facts_b=sorted(f for f in facts_b if _normalize(f) in unique_to_b),
                ))
    return flags
