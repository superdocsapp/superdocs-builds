"""Diffs incoming rule facts (from an amendment or a Q&A response) against
the currently-tracked state (which starts as the solicitation baseline).

Each document is applied as one batch, in arrival order — this mirrors
"stays alive": every new document produces a focused update against
whatever the deliverable already says, not a full re-run from scratch.

Conflict rule (kept deliberately simple and explainable): when an incoming
fact claims a key is *unchanged* (``confirmed_no_change``) but the tracked
state disagrees, that is a real contradiction between sources and is
surfaced as a Conflict rather than silently resolved either way. Everything
else (a new value asserted for an existing or new key) is treated as a
legitimate update and applied — GovCon amendments/Q&A are authoritative over
the document they amend, arriving in a known order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .models import AmendmentDelta, Confirmation, Conflict, ParsedFact

StateKey = Tuple[str, str]


@dataclass
class BatchResult:
    deltas: List[AmendmentDelta] = field(default_factory=list)
    confirmations: List[Confirmation] = field(default_factory=list)
    conflicts: List[Conflict] = field(default_factory=list)


def build_baseline_state(baseline_facts: List[ParsedFact]) -> Dict[StateKey, ParsedFact]:
    state: Dict[StateKey, ParsedFact] = {}
    for fact in baseline_facts:
        state[(fact.rule_type, fact.key)] = fact
    return state


def apply_batch(state: Dict[StateKey, ParsedFact], facts: List[ParsedFact]) -> BatchResult:
    """Apply one document's worth of facts against the current state.

    Mutates ``state`` in place for every fact that is applied (i.e. every
    delta and non-contradicting confirmation), and returns what happened.
    Conflicting facts do NOT mutate state — the old value stands until a
    human resolves the conflict.
    """

    result = BatchResult()

    for fact in facts:
        key = (fact.rule_type, fact.key)
        current = state.get(key)

        if fact.change_kind == "confirmed_no_change":
            if current is None:
                # Nothing on record yet; take the confirmation as the new baseline.
                state[key] = fact
                result.confirmations.append(Confirmation(fact.rule_type, fact.key, fact.value, fact.source))
            elif current.value == fact.value:
                result.confirmations.append(Confirmation(fact.rule_type, fact.key, fact.value, fact.source))
            else:
                result.conflicts.append(
                    Conflict(
                        rule_type=fact.rule_type,
                        key=fact.key,
                        existing_value=current.value,
                        existing_source=current.source,
                        new_value=fact.value,
                        new_source=fact.source,
                    )
                )
            continue

        old_value = current.value if current is not None else None
        if current is not None and current.value == fact.value:
            # Re-stating an already-current value: a no-op, not a delta.
            continue

        delta = AmendmentDelta(
            delta_id=f"delta-{uuid.uuid4().hex[:8]}",
            rule_type=fact.rule_type,
            key=fact.key,
            old_value=old_value,
            new_value=fact.value,
            change_kind=fact.change_kind,
            source=fact.source,
        )
        result.deltas.append(delta)
        state[key] = fact

    return result


def apply_documents(
    baseline_facts: List[ParsedFact], documents: List[List[ParsedFact]]
) -> Tuple[Dict[StateKey, ParsedFact], BatchResult]:
    """Apply a sequence of documents in arrival order; return final state + combined result."""

    state = build_baseline_state(baseline_facts)
    combined = BatchResult()
    for doc_facts in documents:
        r = apply_batch(state, doc_facts)
        combined.deltas.extend(r.deltas)
        combined.confirmations.extend(r.confirmations)
        combined.conflicts.extend(r.conflicts)
    return state, combined
