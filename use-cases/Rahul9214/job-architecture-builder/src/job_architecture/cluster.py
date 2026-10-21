"""Corpus-level clustering from RoleEvidence content.

A cluster is a set of core roles whose occupational similarity is high
enough to merge under average linkage, and whose functional evidence is
compatible.

Similarity is a structured representation, not raw token Jaccard:
- TF-IDF over field-weighted occupational tokens (responsibilities and
  domain first; title never included);
- cosine of family-lexicon score vectors (evidence dimensions, not the
  assigned family label);
- a compatibility gate so two strong, distinct crafts do not merge just
  because they share generic JD language.

Family catalog labels are applied only after groups exist.

Limitations:
- TF-IDF and lexicon scores are small, explicit, and not learned.
- Singleton clusters mean "no neighbor cleared the merge bar".
- Hybrid, sparse, and misfit roles are not absorbed for coverage.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from job_architecture.catalog import FAMILY_ASSIGN_MIN
from job_architecture.evidence import scoring_text
from job_architecture.family import infer_family, infer_family_from_text
from job_architecture.models import FitStatus, RoleAssessment, RoleEvidence
from job_architecture.textutil import UNSTATED, normalize_whitespace

# Average-linkage similarity required to merge two compatible groups.
MERGE_THRESHOLD = 0.28
TFIDF_WEIGHT = 0.70
OCC_WEIGHT = 0.30
# Same-craft roles still need some content overlap. Occupational cosine
# alone must not collapse every role that shares a primary dimension.
TFIDF_MIN = 0.034
# Minimum similarity to call a non-core role a neighbor/bridge.
BRIDGE_MIN = 0.08
# Second-nearest cluster must be this close to the nearest to count as a bridge.
BRIDGE_RATIO = 0.25
# Member is ambiguous when another cluster is this close to in-cluster cohesion.
AMBIGUOUS_DELTA = 0.05
# Both roles must reach this score on each other's primary to count as cross-domain.
CROSS_PRIMARY_MIN = 2.0

_TOKEN_RE = re.compile(r"[a-z]{3,}")

# Generic JD language. Occupational terms are kept; IDF further down-weights
# corpus-wide boilerplate such as employer names that leak into body text.
_STOPWORDS = frozenset(
    """
    the and for with you your this that from are not may than into about
    will can has have been being were was they them their our who what
    when where which while also such other more most some any all both
    each own over after before through during without within across
    including include included required requirements experience preferred
    ability willingness comfort clear written verbal
    role roles team teams work works working
    using used use make made need needs needed
    help helping ensure ensuring drive driving
    owning ownership responsible responsibility
    support supporting supported
    partner partners partnership
    collaborate collaborating collaboration collaborative
    stakeholder stakeholders
    deliver delivering delivery
    project projects
    business
    must should shall via per etc
    strong related how those these then well already
    year years based
    new time every company organization
    internal
    write writing
    run running
    set setting
    reports report reporting
    direct directly
    manager managers
    people
    hire hiring
    coach coaching
    performance
    planning
    influence
    appear cannot
    decide decision decisions
    lead leading leadership
    review reviews
    change changes
    """.split()
)

# Field multipliers for term frequency. Stakeholders name who the role talks
# to, not the craft, so they are omitted from the token vector.
_FIELD_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("responsibilities", 3),
    ("domain", 3),
    ("scope", 1),
    ("complexity", 1),
    ("impact", 1),
    ("autonomy", 1),
    ("leadership", 1),
    ("management", 2),
    ("decision", 1),
)


def similarity_text(evidence: RoleEvidence) -> str:
    """Occupational text used for clustering. Title, team, organization, and
    stakeholder lists are omitted."""
    parts = [
        *evidence.responsibilities,
        evidence.scope if evidence.scope != UNSTATED else "",
        evidence.autonomy if evidence.autonomy != UNSTATED else "",
        evidence.leadership if evidence.leadership != UNSTATED else "",
        evidence.people_management if evidence.people_management != UNSTATED else "",
        evidence.domain_depth if evidence.domain_depth != UNSTATED else "",
        evidence.decision_making_authority,
        evidence.complexity if evidence.complexity != UNSTATED else "",
        evidence.impact if evidence.impact != UNSTATED else "",
    ]
    return normalize_whitespace(" ".join(part for part in parts if part))


def _field_chunks(evidence: RoleEvidence) -> dict[str, str]:
    return {
        "responsibilities": " ".join(evidence.responsibilities),
        "domain": "" if evidence.domain_depth == UNSTATED else evidence.domain_depth,
        "scope": "" if evidence.scope == UNSTATED else evidence.scope,
        "complexity": "" if evidence.complexity == UNSTATED else evidence.complexity,
        "impact": "" if evidence.impact == UNSTATED else evidence.impact,
        "autonomy": "" if evidence.autonomy == UNSTATED else evidence.autonomy,
        "leadership": "" if evidence.leadership == UNSTATED else evidence.leadership,
        "management": "" if evidence.people_management == UNSTATED else evidence.people_management,
        "decision": evidence.decision_making_authority,
    }


def tokenize_evidence(text: str, extra_stops: Iterable[str] = ()) -> frozenset[str]:
    banned = _STOPWORDS | {token.lower() for token in extra_stops}
    return frozenset(token for token in _TOKEN_RE.findall(text.lower()) if token not in banned)


def _token_stream(text: str, extra_stops: frozenset[str]) -> list[str]:
    words = [token for token in _TOKEN_RE.findall(text.lower()) if token not in extra_stops]
    tokens = list(words)
    for left, right in zip(words, words[1:]):
        tokens.append(f"{left}_{right}")
    return tokens


def _name_tokens(evidences: Sequence[RoleEvidence]) -> frozenset[str]:
    """Employer-name tokens, derived from the corpus rather than hardcoded."""
    tokens: set[str] = set()
    for item in evidences:
        tokens.update(_TOKEN_RE.findall(item.organization.lower()))
    return frozenset(token for token in tokens if token not in _STOPWORDS)


def evidence_signature(evidence: RoleEvidence) -> tuple[str, ...]:
    extra = tokenize_evidence(evidence.organization)
    return tuple(sorted(tokenize_evidence(similarity_text(evidence), extra)))


def cosine(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if not left or not right:
        return 0.0
    shared = 0.0
    for key, value in left.items():
        other = right.get(key)
        if other:
            shared += value * other
    if shared <= 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return round(shared / (left_norm * right_norm), 6)


@dataclass(frozen=True)
class RoleVector:
    role_id: str
    tokens: tuple[str, ...]
    tfidf: dict[str, float]
    occ_scores: dict[str, float]
    primary: str | None

    @property
    def token_set(self) -> frozenset[str]:
        return frozenset(self.tokens)


@dataclass(frozen=True)
class RoleSignature:
    role_id: str
    tokens: tuple[str, ...]
    primary: str | None = None

    @property
    def token_set(self) -> frozenset[str]:
        return frozenset(self.tokens)


@dataclass(frozen=True)
class ClusterMember:
    role_id: str
    cohesion: float
    nearest_other_cluster_id: str | None
    nearest_other_similarity: float | None
    is_ambiguous: bool


@dataclass(frozen=True)
class RoleCluster:
    cluster_id: str
    member_role_ids: tuple[str, ...]
    proposed_family: str | None
    cohesion: float
    members: tuple[ClusterMember, ...]
    nearest_cluster_id: str | None
    nearest_cluster_similarity: float | None
    ambiguous_role_ids: tuple[str, ...]
    notes: str
    label_confidence: float | None = None
    separation: float | None = None


@dataclass(frozen=True)
class BridgeAssignment:
    role_id: str
    nearest_cluster_id: str | None
    nearest_similarity: float
    alternative_cluster_id: str | None
    alternative_similarity: float | None
    is_bridge: bool


@dataclass(frozen=True)
class ClusteringResult:
    signatures: tuple[RoleSignature, ...]
    clusters: tuple[RoleCluster, ...]
    unclustered_role_ids: tuple[str, ...]
    bridge_role_ids: tuple[str, ...]
    bridges: tuple[BridgeAssignment, ...]
    vectors: tuple[RoleVector, ...] = ()

    def cluster_for_role(self, role_id: str) -> RoleCluster | None:
        for cluster in self.clusters:
            if role_id in cluster.member_role_ids:
                return cluster
        return None

    def signature_for(self, role_id: str) -> RoleSignature:
        for item in self.signatures:
            if item.role_id == role_id:
                return item
        raise KeyError(role_id)

    def vector_for(self, role_id: str) -> RoleVector:
        for item in self.vectors:
            if item.role_id == role_id:
                return item
        raise KeyError(role_id)


def _occupational_scores(evidence: RoleEvidence) -> dict[str, float]:
    inference = infer_family(evidence)
    return {key: max(0.0, value) for key, value in inference.scores.items()}


def _primary_dimension(scores: Mapping[str, float]) -> str | None:
    catalog = {key: value for key, value in scores.items() if not key.startswith("_")}
    if not catalog:
        return None
    family_id, value = max(catalog.items(), key=lambda item: (item[1], item[0]))
    if value < FAMILY_ASSIGN_MIN:
        return None
    return family_id


def occupationally_compatible(left: RoleVector, right: RoleVector) -> bool:
    """True when two roles may share a cluster.

    Same strong primary is compatible. Distinct strong primaries require
    each role to carry the other's craft at CROSS_PRIMARY_MIN. Weak or
    missing primaries do not block token-based grouping.
    """
    left_primary = left.primary
    right_primary = right.primary
    if left_primary is None or right_primary is None:
        return True
    if left_primary == right_primary:
        return True
    return (
        left.occ_scores.get(right_primary, 0.0) >= CROSS_PRIMARY_MIN
        and right.occ_scores.get(left_primary, 0.0) >= CROSS_PRIMARY_MIN
    )


def _tf_map(evidence: RoleEvidence, extra_stops: frozenset[str]) -> dict[str, float]:
    counts: dict[str, float] = {}
    chunks = _field_chunks(evidence)
    for field_name, weight in _FIELD_WEIGHTS:
        if weight <= 0:
            continue
        for token in _token_stream(chunks.get(field_name, ""), extra_stops):
            counts[token] = counts.get(token, 0.0) + weight
    return counts


def build_vectors(evidences: Sequence[RoleEvidence]) -> dict[str, RoleVector]:
    extra_stops = _STOPWORDS | _name_tokens(evidences)
    term_frequencies = {item.role_id: _tf_map(item, extra_stops) for item in evidences}
    document_frequency: dict[str, int] = {}
    for counts in term_frequencies.values():
        for token in counts:
            document_frequency[token] = document_frequency.get(token, 0) + 1
    n_docs = max(len(evidences), 1)
    vectors: dict[str, RoleVector] = {}
    for item in evidences:
        counts = term_frequencies[item.role_id]
        tfidf: dict[str, float] = {}
        for token, raw_tf in counts.items():
            idf = math.log((n_docs + 1) / (document_frequency[token] + 1)) + 1.0
            tfidf[token] = math.log(1.0 + raw_tf) * idf
        scores = _occupational_scores(item)
        vectors[item.role_id] = RoleVector(
            role_id=item.role_id,
            tokens=tuple(sorted(tokenize_evidence(similarity_text(item), extra_stops))),
            tfidf=tfidf,
            occ_scores=scores,
            primary=_primary_dimension(scores),
        )
    return vectors


def content_similarity(left: RoleVector, right: RoleVector) -> float:
    """Ungated mix of TF-IDF and occupational cosine. Used for bridges."""
    tfidf = cosine(left.tfidf, right.tfidf)
    occ = cosine(
        {key: value for key, value in left.occ_scores.items() if not key.startswith("_")},
        {key: value for key, value in right.occ_scores.items() if not key.startswith("_")},
    )
    return round(TFIDF_WEIGHT * tfidf + OCC_WEIGHT * occ, 6)


def pair_similarity(left: RoleVector, right: RoleVector) -> float:
    """Merge similarity: compatible crafts with real content overlap."""
    if not occupationally_compatible(left, right):
        return 0.0
    tfidf = cosine(left.tfidf, right.tfidf)
    if tfidf < TFIDF_MIN:
        return 0.0
    return content_similarity(left, right)


def pairwise_similarity(vectors: Mapping[str, RoleVector]) -> dict[tuple[str, str], float]:
    role_ids = sorted(vectors)
    pairs: dict[tuple[str, str], float] = {}
    for index, left in enumerate(role_ids):
        for right in role_ids[index + 1 :]:
            pairs[(left, right)] = pair_similarity(vectors[left], vectors[right])
    return pairs


def _pair_value(
    left_id: str,
    right_id: str,
    sims: Mapping[tuple[str, str], float],
) -> float:
    if left_id == right_id:
        return 1.0
    key = (left_id, right_id) if left_id < right_id else (right_id, left_id)
    return sims.get(key, 0.0)


def nearest_neighbors(
    vectors: Mapping[str, RoleVector],
    role_id: str,
    *,
    k: int = 3,
    exclude: Iterable[str] = (),
) -> tuple[tuple[str, float], ...]:
    banned = set(exclude) | {role_id}
    ranked = sorted(
        (
            (other, pair_similarity(vectors[role_id], vector))
            for other, vector in vectors.items()
            if other not in banned
        ),
        key=lambda item: (-item[1], item[0]),
    )
    return tuple(ranked[:k])


def _average_linkage(
    left: Sequence[str],
    right: Sequence[str],
    sims: Mapping[tuple[str, str], float],
) -> float:
    """Mean similarity of pairs that cleared the content floor.

    Pairs below TFIDF_MIN do not vote. That keeps a large craft neighborhood
    from being blocked by one distant member, and keeps unrelated same-primary
    roles from chaining in without content overlap.
    """
    supported = [
        _pair_value(left_id, right_id, sims)
        for left_id in left
        for right_id in right
        if _pair_value(left_id, right_id, sims) > 0
    ]
    if not supported:
        return 0.0
    return sum(supported) / len(supported)


def _agglomerative_clusters(
    core_ids: Sequence[str],
    sims: Mapping[tuple[str, str], float],
    threshold: float,
) -> list[list[str]]:
    clusters = [[role_id] for role_id in sorted(core_ids)]
    while True:
        best_sim = -1.0
        best_pair: tuple[int, int] | None = None
        best_key: tuple[str, str] | None = None
        for i, left in enumerate(clusters):
            for j, right in enumerate(clusters[i + 1 :], start=i + 1):
                sim = _average_linkage(left, right, sims)
                if sim < threshold:
                    continue
                key = (min(left[0], right[0]), max(left[0], right[0]))
                if sim > best_sim or (sim == best_sim and (best_key is None or key < best_key)):
                    best_sim = sim
                    best_pair = (i, j)
                    best_key = key
        if best_pair is None:
            break
        i, j = best_pair
        merged = sorted(clusters[i] + clusters[j])
        clusters = [group for index, group in enumerate(clusters) if index not in best_pair]
        clusters.append(merged)
        clusters.sort(key=lambda group: group[0])
    return clusters


def _mean_to_group(
    role_id: str,
    group: Sequence[str],
    sims: Mapping[tuple[str, str], float],
) -> float:
    others = [item for item in group if item != role_id]
    if not others:
        return 1.0
    return sum(_pair_value(role_id, other, sims) for other in others) / len(others)


def _mean_tfidf(
    left_ids: Sequence[str],
    right_ids: Sequence[str],
    vectors: Mapping[str, RoleVector],
) -> float:
    total = 0.0
    count = 0
    for left_id in left_ids:
        for right_id in right_ids:
            total += cosine(vectors[left_id].tfidf, vectors[right_id].tfidf)
            count += 1
    return total / count if count else 0.0


def _mean_pairwise(members: Sequence[str], sims: Mapping[tuple[str, str], float]) -> float:
    if len(members) <= 1:
        return 1.0
    total = 0.0
    count = 0
    for index, left in enumerate(members):
        for right in members[index + 1 :]:
            total += _pair_value(left, right, sims)
            count += 1
    return total / count if count else 0.0


def eligibility_sets(
    assessments: Sequence[RoleAssessment],
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return (core_ids, bridge_candidate_ids, excluded_ids)."""
    core: set[str] = set()
    bridges: set[str] = set()
    excluded: set[str] = set()
    for item in assessments:
        codes = {reason.code for reason in item.misfit_reasons}
        if item.fit_status is FitStatus.MISFIT or "outside_architecture" in codes:
            excluded.add(item.role_id)
        elif "insufficient_evidence" in codes:
            excluded.add(item.role_id)
        elif "hybrid_unresolved" in codes or (
            item.fit_status is FitStatus.PROVISIONAL and item.proposed_family is None
        ):
            bridges.add(item.role_id)
        else:
            core.add(item.role_id)
    return frozenset(core), frozenset(bridges), frozenset(excluded)


def _label_cluster(members: Sequence[str], by_id: Mapping[str, RoleEvidence]) -> tuple[str | None, float | None, str]:
    blob = " ".join(scoring_text(by_id[role_id]) for role_id in members)
    family = infer_family_from_text(blob)
    if family.is_hybrid or family.is_outside or family.family_id is None:
        return (None, None, "Grouped by similarity; catalog did not assign a single family label.")
    real = {key: value for key, value in family.scores.items() if not key.startswith("_")}
    ranked = sorted(real.values(), reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else 0.0
    confidence = round(top / (top + second + 1e-6), 4)
    notes = "Labeled from aggregated member evidence after grouping."
    return (family.family_id, confidence, notes)


def cluster_corpus(
    evidences: Sequence[RoleEvidence],
    assessments: Sequence[RoleAssessment],
) -> ClusteringResult:
    by_id = {item.role_id: item for item in evidences}
    vectors = build_vectors(evidences)
    sims = pairwise_similarity(vectors)
    signatures = tuple(
        RoleSignature(role_id=item.role_id, tokens=item.tokens, primary=item.primary)
        for item in sorted(vectors.values(), key=lambda row: row.role_id)
    )
    core_ids, bridge_ids, excluded_ids = eligibility_sets(assessments)
    raw_groups = _agglomerative_clusters(sorted(core_ids), sims, MERGE_THRESHOLD)

    labeled: list[RoleCluster] = []
    for index, members in enumerate(raw_groups, start=1):
        cluster_id = f"cluster-{index:02d}"
        cohesion = _mean_pairwise(members, sims)
        proposed_family, label_confidence, notes = _label_cluster(members, by_id)
        labeled.append(
            RoleCluster(
                cluster_id=cluster_id,
                member_role_ids=tuple(members),
                proposed_family=proposed_family,
                cohesion=round(cohesion, 4),
                members=(),
                nearest_cluster_id=None,
                nearest_cluster_similarity=None,
                ambiguous_role_ids=(),
                notes=notes,
                label_confidence=label_confidence,
                separation=None,
            )
        )

    filled: list[RoleCluster] = []
    for cluster in labeled:
        nearest_id = None
        nearest_sim = None
        for other in labeled:
            if other.cluster_id == cluster.cluster_id:
                continue
            sim = _average_linkage(cluster.member_role_ids, other.member_role_ids, sims)
            if sim <= 0:
                continue
            if nearest_sim is None or sim > nearest_sim:
                nearest_sim = sim
                nearest_id = other.cluster_id
        if nearest_sim is None:
            for other in labeled:
                if other.cluster_id == cluster.cluster_id:
                    continue
                sim = _mean_tfidf(cluster.member_role_ids, other.member_role_ids, vectors)
                if nearest_sim is None or sim > nearest_sim:
                    nearest_sim = sim
                    nearest_id = other.cluster_id
        member_rows: list[ClusterMember] = []
        ambiguous: list[str] = []
        for role_id in cluster.member_role_ids:
            cohesion = _mean_to_group(role_id, cluster.member_role_ids, sims)
            other_id = None
            other_sim = None
            for other in labeled:
                if other.cluster_id == cluster.cluster_id:
                    continue
                sim = _mean_to_group(role_id, other.member_role_ids, sims)
                if sim <= 0:
                    continue
                if other_sim is None or sim > other_sim:
                    other_sim = sim
                    other_id = other.cluster_id
            is_ambiguous = (
                other_sim is not None
                and cohesion - other_sim <= AMBIGUOUS_DELTA
                and other_sim >= BRIDGE_MIN
            )
            if is_ambiguous:
                ambiguous.append(role_id)
            member_rows.append(
                ClusterMember(
                    role_id=role_id,
                    cohesion=round(cohesion, 4),
                    nearest_other_cluster_id=other_id,
                    nearest_other_similarity=None if other_sim is None else round(other_sim, 4),
                    is_ambiguous=is_ambiguous,
                )
            )
        separation = None if nearest_sim is None else round(cluster.cohesion - nearest_sim, 4)
        filled.append(
            RoleCluster(
                cluster_id=cluster.cluster_id,
                member_role_ids=cluster.member_role_ids,
                proposed_family=cluster.proposed_family,
                cohesion=cluster.cohesion,
                members=tuple(member_rows),
                nearest_cluster_id=nearest_id,
                nearest_cluster_similarity=None if nearest_sim is None else round(nearest_sim, 4),
                ambiguous_role_ids=tuple(ambiguous),
                notes=cluster.notes,
                label_confidence=cluster.label_confidence,
                separation=separation,
            )
        )

    bridges: list[BridgeAssignment] = []
    bridge_role_ids: list[str] = []
    for role_id in sorted(bridge_ids):
        ranked = sorted(
            (
                (
                    cluster.cluster_id,
                    (
                        sum(
                            content_similarity(vectors[role_id], vectors[member_id])
                            for member_id in cluster.member_role_ids
                        )
                        / len(cluster.member_role_ids)
                        if cluster.member_role_ids
                        else 0.0
                    ),
                )
                for cluster in filled
            ),
            key=lambda item: (-item[1], item[0]),
        )
        nearest = ranked[0] if ranked else ("", 0.0)
        alternative = ranked[1] if len(ranked) > 1 else ("", 0.0)
        is_bridge = (
            nearest[1] >= BRIDGE_MIN
            and alternative[1] >= BRIDGE_MIN
            and alternative[1] >= nearest[1] * BRIDGE_RATIO
        )
        if is_bridge or nearest[1] >= BRIDGE_MIN:
            bridge_role_ids.append(role_id)
        bridges.append(
            BridgeAssignment(
                role_id=role_id,
                nearest_cluster_id=nearest[0] or None,
                nearest_similarity=round(nearest[1], 4),
                alternative_cluster_id=alternative[0] or None if alternative[1] else None,
                alternative_similarity=round(alternative[1], 4) if alternative[1] else None,
                is_bridge=is_bridge,
            )
        )

    unclustered = tuple(sorted(set(excluded_ids) | set(bridge_ids)))
    return ClusteringResult(
        signatures=signatures,
        clusters=tuple(filled),
        unclustered_role_ids=unclustered,
        bridge_role_ids=tuple(bridge_role_ids),
        bridges=tuple(bridges),
        vectors=tuple(vectors[role_id] for role_id in sorted(vectors)),
    )
