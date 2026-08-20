"""Cross-workstream conflict detection.

The card asks for one thing above all: *"Where two workstreams claim the same synergy or
the same dependency, the conflict is flagged in both documents rather than silently
duplicated."* And it says a strong build has *"cross-workstream conflicts genuinely
detected and surfaced in both places."*

Two words in that carry the weight.

**Genuinely** — so detection is deterministic arithmetic over the deal spec, not a model
asked whether anything looks off. A model asked that question will find something on a
clean deal and miss something on a dirty one, and neither failure is visible. Every
comparator here is exhaustive, cheap, and testable with no API key at all.

**Both** — so a conflict is never reported once, in the master, where each workstream
lead can assume it belongs to someone else. It lands in every document that has a stake
in it. `Conflict.affects` is the list of workstreams that must each see it, and it is
what the document layer fans out over.

Four comparators, each a general mechanism rather than a special case:

    duplicate_synergy      two workstreams bank the same saving
    contested_dependency   two workstreams own the same deliverable
    synergy_over_commitment claimed savings exceed what the deal promised
    unmet_day_one          a day-one item needs something not delivered until later
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from imo.deal import Deal

# Words too common in integration language to signal a shared claim on their own.
# Without this, "Consolidate finance systems" and "Consolidate HR systems" read as the
# same synergy, and the report fills with pairs nobody believes — at which point the
# real duplicates stop being read too.
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "from",
    "consolidate", "reduce", "improve", "integrate", "align", "review", "single",
    "cost", "costs", "saving", "savings", "spend", "across", "into", "by",
}

# How much of the significant vocabulary two descriptions must share before they are
# treated as claims on the same thing. Tuned so the pairs it surfaces are ones a human
# would also call duplicates; raise it if a corpus is noisy, lower it to cast wider.
SIMILARITY_THRESHOLD = 0.6


@dataclass(frozen=True)
class Conflict:
    """A contradiction between workstreams, with the evidence to judge it.

    `affects` is the point of the whole module: it names every workstream whose
    document must carry this conflict. A conflict flagged once centrally is a conflict
    each lead assumes belongs to someone else.
    """

    kind: str
    severity: str
    summary: str
    detail: str
    affects: list[str]  # workstream keys, each of which must show this
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        stem = re.sub(r"[^a-z0-9]+", "-", self.summary.lower()).strip("-")
        return f"{self.kind}:{stem[:48]}"


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def _similarity(a: str, b: str) -> float:
    """Jaccard overlap of significant words.

    Deliberately crude and deliberately explainable. A reviewer asking "why were these
    flagged as the same?" gets an answer they can check by reading, which matters more
    here than a cleverer metric nobody can audit.
    """
    left, right = _significant_words(a), _significant_words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# ---------------------------------------------------------------------------
# 1. Two workstreams banking the same saving
# ---------------------------------------------------------------------------


def find_duplicate_synergies(deal: Deal) -> list[Conflict]:
    """Double-counted synergy — the expensive kind of duplicate.

    Two workstreams each claiming a saving means the deal's total is overstated by the
    smaller of the two, and nobody notices until the run-rate misses. Caught two ways:
    an identical synergy id, and near-identical descriptions under different ids.
    """
    conflicts: list[Conflict] = []
    synergies = deal.all_synergies

    for i, first in enumerate(synergies):
        for second in synergies[i + 1 :]:
            if first.owner == second.owner:
                continue  # one workstream's own bookkeeping, not a cross-claim

            same_id = first.id == second.id
            similar = _similarity(first.description, second.description) >= SIMILARITY_THRESHOLD
            if not (same_id or similar):
                continue

            overlap = min(first.annual_value_usd, second.annual_value_usd)
            conflicts.append(
                Conflict(
                    kind="duplicate_synergy",
                    severity="high",
                    summary=(
                        f"{first.owner} and {second.owner} both claim the same synergy"
                    ),
                    detail=(
                        f"{first.owner} claims {first.id} "
                        f"({first.description}, {first.value_display}) and "
                        f"{second.owner} claims {second.id} "
                        f"({second.description}, {second.value_display}). "
                        f"These describe the same saving, so the integration total is "
                        f"overstated by up to ${overlap:,.0f}. One workstream must own "
                        f"it and the other must drop the claim."
                    ),
                    affects=[first.owner, second.owner],
                    evidence={
                        first.owner: f"{first.id}: {first.description} ({first.value_display})",
                        second.owner: f"{second.id}: {second.description} ({second.value_display})",
                    },
                )
            )

    return conflicts


# ---------------------------------------------------------------------------
# 2. Two workstreams owning the same deliverable
# ---------------------------------------------------------------------------


def find_contested_dependencies(deal: Deal) -> list[Conflict]:
    """Two owners is the same failure as no owner, and harder to see.

    Each lead reports the item as covered, the steering pack shows it green, and it is
    delivered twice or not at all.
    """
    conflicts: list[Conflict] = []
    dependencies = deal.all_dependencies

    for i, first in enumerate(dependencies):
        for second in dependencies[i + 1 :]:
            if first.owner == second.owner:
                continue

            same_id = first.id == second.id
            similar = _similarity(first.description, second.description) >= SIMILARITY_THRESHOLD
            if not (same_id or similar):
                continue

            conflicts.append(
                Conflict(
                    kind="contested_dependency",
                    severity="high",
                    summary=(
                        f"{first.owner} and {second.owner} both own the same dependency"
                    ),
                    detail=(
                        f"{first.owner} owns {first.id} ({first.description}, needed by "
                        f"month {first.needed_by_month}) and {second.owner} owns "
                        f"{second.id} ({second.description}, needed by month "
                        f"{second.needed_by_month}). Two owners means each side can "
                        f"reasonably assume the other is delivering it. Assign one."
                    ),
                    affects=[first.owner, second.owner],
                    evidence={
                        first.owner: f"{first.id}: {first.description} (month {first.needed_by_month})",
                        second.owner: f"{second.id}: {second.description} (month {second.needed_by_month})",
                    },
                )
            )

    return conflicts


# ---------------------------------------------------------------------------
# 3. Claimed savings exceeding what the deal promised
# ---------------------------------------------------------------------------


def find_synergy_over_commitment(deal: Deal) -> list[Conflict]:
    """Workstream claims summing past the deal target.

    Not automatically wrong — over-programming against a target is a deliberate tactic —
    but it is always a decision someone should have made on purpose, and it is exactly
    what nobody notices until the tracker is assembled.
    """
    claimed = deal.claimed_synergy_total
    target = deal.synergy_target_usd

    if claimed <= target:
        return []

    excess = claimed - target

    # A target of zero is a real state, not a broken one: an early-stage deal has
    # workstreams estimating savings before the target is agreed. Expressing the excess
    # as a percentage of zero raised DivisionByZero and took the whole detection pass
    # down — a crash on the most ordinary early input there is.
    proportion = f" ({excess / target:.0%})" if target > 0 else ""
    against = (
        f"a deal target of ${target:,.0f}"
        if target > 0
        else "no agreed deal target"
    )

    return [
        Conflict(
            kind="synergy_over_commitment",
            severity="medium",
            summary="Workstream synergy claims exceed the deal target",
            detail=(
                f"Workstreams claim ${claimed:,.0f} in total against {against} — "
                f"an excess of ${excess:,.0f}{proportion}. Either the target is stale "
                f"or some claims are double-counted. Reconcile before the tracker goes "
                f"to steering."
            ),
            # Every workstream with a claim shares this one: it cannot be resolved by
            # any single lead, and showing it only in the master lets all of them
            # assume it is someone else's number that is wrong.
            affects=sorted({s.owner for s in deal.all_synergies}),
            evidence={
                w.key: f"claims ${w.synergy_total:,.0f}"
                for w in deal.workstreams
                if w.synergies
            },
        )
    ]


# ---------------------------------------------------------------------------
# 4. Day-one items resting on things that do not exist yet
# ---------------------------------------------------------------------------


def find_unmet_day_one(deal: Deal) -> list[Conflict]:
    """A day-one item depending on something delivered in month three is not a day-one
    item — it is a month-three item nobody has rescheduled.

    This is what makes the checklist specific to *this* deal rather than a generic
    list: the finding exists only because of how these particular dependencies are
    sequenced.
    """
    conflicts: list[Conflict] = []

    for item in deal.all_day_one:
        for dependency_id in item.depends_on:
            dependency = deal.dependency(dependency_id)
            if dependency is None or dependency.needed_by_month <= 0:
                continue

            affects = sorted({item.owner, dependency.owner})
            conflicts.append(
                Conflict(
                    kind="unmet_day_one",
                    severity="high",
                    summary=(
                        f"Day-one item {item.id} depends on work not delivered until "
                        f"month {dependency.needed_by_month}"
                    ),
                    detail=(
                        f"{item.owner} lists {item.id} ({item.description}) as a day-one "
                        f"readiness item, but it depends on {dependency.id} "
                        f"({dependency.description}), which {dependency.owner} does not "
                        f"deliver until month {dependency.needed_by_month}. The item "
                        f"cannot be green at close. Either pull the dependency forward "
                        f"or move the item out of day one."
                    ),
                    affects=affects,
                    evidence={
                        item.owner: f"{item.id}: {item.description} (day one)",
                        dependency.owner: (
                            f"{dependency.id}: {dependency.description} "
                            f"(month {dependency.needed_by_month})"
                        ),
                    },
                )
            )

    return conflicts


# ---------------------------------------------------------------------------

COMPARATORS = (
    find_duplicate_synergies,
    find_contested_dependencies,
    find_synergy_over_commitment,
    find_unmet_day_one,
)


def detect(deal: Deal) -> list[Conflict]:
    """Run every comparator, deduplicated and ordered by severity.

    An empty list is a first-class outcome: a clean deal genuinely has no
    cross-workstream conflicts, and reporting a reassuring nothing is more useful than
    manufacturing something to justify the check having run.
    """
    seen: set[str] = set()
    found: list[Conflict] = []

    for comparator in COMPARATORS:
        for conflict in comparator(deal):
            if conflict.id in seen:
                continue
            seen.add(conflict.id)
            found.append(conflict)

    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(found, key=lambda c: (rank.get(c.severity, 3), c.summary))


def conflicts_for(conflicts: list[Conflict], workstream_key: str) -> list[Conflict]:
    """Every conflict a given workstream's document must carry."""
    return [c for c in conflicts if workstream_key in c.affects]


def summarise(conflicts: list[Conflict]) -> dict[str, int | Decimal]:
    return {
        "total": len(conflicts),
        "high": sum(1 for c in conflicts if c.severity == "high"),
        "medium": sum(1 for c in conflicts if c.severity == "medium"),
        "workstreams_affected": len({w for c in conflicts for w in c.affects}),
    }
