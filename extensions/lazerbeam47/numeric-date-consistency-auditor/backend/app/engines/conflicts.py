"""Cross-document conflict engine (Project 1 core).

Facts from different documents are grouped into *claim clusters* — the same
subject asserted more than once — and each cluster is checked for
contradictions. Clustering uses a cheap deterministic key first (normalised
label + fact type) and optional embedding similarity second, so the engine
works with zero LLM budget and gets sharper when embeddings are available.

Output is always a Finding with citations from *both* sides of the conflict:
a conflict without provenance is an accusation, not a result.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from app.core.config import get_settings
from app.engines.normalization import close_enough, format_money
from app.schemas.domain import (
    Citation,
    Fact,
    FactType,
    Finding,
    FindingCategory,
    Severity,
)

settings = get_settings()

_STOPWORDS = {"the", "a", "an", "of", "for", "and", "total", "value", "amount"}

NUMERIC_TYPES = {
    FactType.CURRENCY,
    FactType.PERCENTAGE,
    FactType.FINANCIAL_METRIC,
    FactType.REVENUE,
    FactType.PROFIT,
    FactType.EXPENSE,
    FactType.NET_INCOME,
    FactType.TAX,
    FactType.NUMBER,
}
DATE_TYPES = {FactType.DATE, FactType.DEADLINE}
TEXT_TYPES = {
    FactType.PERSON,
    FactType.COMPANY,
    FactType.ADDRESS,
    FactType.INVOICE_NUMBER,
    FactType.GST_NUMBER,
    FactType.OBLIGATION,
    FactType.DELIVERABLE,
}


def normalize_label(label: str) -> str:
    tokens = [t for t in re.split(r"[^a-z0-9]+", (label or "").lower()) if t]
    meaningful_tokens = [token for token in tokens if token not in _STOPWORDS]
    # A label such as "Total" consists solely of a stopword but still names a
    # comparable claim. Falling back to the raw value here would make each
    # numeric value its own cluster and hide exactly the contradiction we need
    # to surface.
    return " ".join(sorted(set(meaningful_tokens or tokens)))


def cosine(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(slots=True)
class ClaimCluster:
    """A set of facts asserting the same thing, ideally across documents."""

    key: str
    fact_type: FactType
    facts: list[Fact] = field(default_factory=list)

    @property
    def document_ids(self) -> set:
        return {f.document_id for f in self.facts if f.document_id}

    @property
    def cross_document(self) -> bool:
        return len(self.document_ids) > 1


def build_clusters(facts: list[Fact], *, similarity_threshold: float = 0.86) -> list[ClaimCluster]:
    """Group facts by normalised label, then merge near-duplicate labels using
    embeddings when they are present. Deterministic first, semantic second."""
    exact: dict[tuple[FactType, str], ClaimCluster] = {}
    for fact in facts:
        key = normalize_label(fact.label) or normalize_label(fact.raw_value)
        if not key:
            continue
        bucket = exact.setdefault(
            (fact.fact_type, key), ClaimCluster(key=key, fact_type=fact.fact_type)
        )
        bucket.facts.append(fact)

    clusters = list(exact.values())

    # Semantic merge pass (no-op when embeddings are absent).
    merged: list[ClaimCluster] = []
    for cluster in clusters:
        centroid = next((f.embedding for f in cluster.facts if f.embedding), None)
        target = None
        if centroid:
            for candidate in merged:
                if candidate.fact_type is not cluster.fact_type:
                    continue
                other = next((f.embedding for f in candidate.facts if f.embedding), None)
                if other and cosine(centroid, other) >= similarity_threshold:
                    target = candidate
                    break
        if target:
            target.facts.extend(cluster.facts)
        else:
            merged.append(cluster)
    return merged


def _citation(fact: Fact) -> Citation:
    return fact.citation or Citation(
        document_id=fact.document_id,
        page=fact.page,
        section=fact.section,
        paragraph=fact.paragraph,
        quote=fact.raw_value,
    )


def _evidence(fact: Fact) -> str:
    doc = f"doc {str(fact.document_id)[:8]}" if fact.document_id else "document"
    return f"{doc} · {_citation(fact).locator}: \"{fact.raw_value}\""


def _finding(
    cluster: ClaimCluster,
    *,
    finding_type: str,
    title: str,
    explanation: str,
    severity: Severity,
    confidence: float,
    facts: list[Fact],
    expected: str | None,
    actual: str | None,
    difference: str | None,
    suggestion: str,
) -> Finding:
    return Finding(
        category=FindingCategory.CONFLICT,
        finding_type=finding_type,
        severity=severity,
        confidence=confidence,
        title=title,
        explanation=explanation,
        expected_value=expected,
        actual_value=actual,
        difference=difference,
        suggested_correction=suggestion,
        evidence=[_evidence(f) for f in facts],
        citations=[_citation(f) for f in facts],
        related_fact_ids=[f.id for f in facts],
        document_id=facts[0].document_id if facts else None,
    )


def _scope(cluster: ClaimCluster) -> str:
    return "across documents" if cluster.cross_document else "within the same document"


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------


def detect_numeric_conflicts(cluster: ClaimCluster) -> list[Finding]:
    if cluster.fact_type not in NUMERIC_TYPES:
        return []
    valued = [(f, f.numeric_value) for f in cluster.facts if f.numeric_value is not None]
    if len(valued) < 2:
        return []

    findings: list[Finding] = []
    for (fa, va), (fb, vb) in combinations(valued, 2):
        currency_a = fa.normalized_value.get("currency")
        currency_b = fb.normalized_value.get("currency")
        if currency_a and currency_b and currency_a != currency_b:
            # Different currencies are not comparable; report the mismatch itself.
            findings.append(
                _finding(
                    cluster,
                    finding_type="currency_mismatch",
                    title=f"'{cluster.key}' is stated in two currencies",
                    explanation=(
                        f"The same figure appears as {format_money(va, currency_a)} and "
                        f"{format_money(vb, currency_b)} {_scope(cluster)}. Without a stated "
                        "conversion rate these values cannot be reconciled."
                    ),
                    severity=Severity.HIGH,
                    confidence=0.88,
                    facts=[fa, fb],
                    expected=format_money(va, currency_a),
                    actual=format_money(vb, currency_b),
                    difference="incomparable units",
                    suggestion="State both amounts in one currency, or record the FX rate used.",
                )
            )
            continue
        if close_enough(va, vb, settings.arithmetic_tolerance):
            continue

        spread = abs(va - vb)
        relative = spread / max(abs(va), abs(vb), 1e-9)
        severity = (
            Severity.CRITICAL if relative >= 0.10 else Severity.HIGH if relative >= 0.02 else Severity.MEDIUM
        )
        findings.append(
            _finding(
                cluster,
                finding_type="numeric_conflict",
                title=f"Conflicting values for '{cluster.key}'",
                explanation=(
                    f"'{fa.label or cluster.key}' is stated as {format_money(va, currency_a)} in one "
                    f"place and {format_money(vb, currency_b)} in another {_scope(cluster)}. "
                    f"The gap is {format_money(spread, currency_a)} ({relative * 100:.2f}%), which "
                    "exceeds rounding tolerance, so the two statements cannot both be true."
                ),
                severity=severity,
                confidence=0.93,
                facts=[fa, fb],
                expected=format_money(va, currency_a),
                actual=format_money(vb, currency_b),
                difference=f"{format_money(spread, currency_a)} ({relative * 100:.2f}%)",
                suggestion=(
                    "Identify the authoritative source document and restate the other occurrence "
                    "to match it."
                ),
            )
        )
    return findings


def detect_date_conflicts(cluster: ClaimCluster) -> list[Finding]:
    if cluster.fact_type not in DATE_TYPES:
        return []
    valued = [(f, f.date_value) for f in cluster.facts if f.date_value is not None]
    if len(valued) < 2:
        return []
    findings: list[Finding] = []
    for (fa, da), (fb, db) in combinations(valued, 2):
        if da == db:
            continue
        gap = abs((da - db).days)
        findings.append(
            _finding(
                cluster,
                finding_type="date_conflict",
                title=f"Conflicting dates for '{cluster.key}'",
                explanation=(
                    f"'{cluster.key}' is given as {da.isoformat()} and {db.isoformat()} "
                    f"{_scope(cluster)} — a {gap} day discrepancy. Deadlines derived from this "
                    "field will differ depending on which document is trusted."
                ),
                severity=Severity.HIGH if gap > 1 else Severity.MEDIUM,
                confidence=0.9,
                facts=[fa, fb],
                expected=da.isoformat(),
                actual=db.isoformat(),
                difference=f"{gap} days",
                suggestion="Align both documents to the executed/authoritative date.",
            )
        )
    return findings


def detect_text_conflicts(cluster: ClaimCluster) -> list[Finding]:
    if cluster.fact_type not in TEXT_TYPES:
        return []
    seen: dict[str, Fact] = {}
    for fact in cluster.facts:
        norm = re.sub(r"\s+", " ", (fact.raw_value or "").strip().lower())
        if norm:
            seen.setdefault(norm, fact)
    if len(seen) < 2:
        return []
    facts = list(seen.values())
    values = list(seen.keys())
    return [
        _finding(
            cluster,
            finding_type="entity_conflict",
            title=f"'{cluster.key}' has {len(values)} different values",
            explanation=(
                f"The same field resolves to {' | '.join(repr(v) for v in values)} {_scope(cluster)}. "
                "Identifier and party mismatches break downstream matching (payment, KYC, routing)."
            ),
            severity=Severity.HIGH
            if cluster.fact_type in (FactType.INVOICE_NUMBER, FactType.GST_NUMBER)
            else Severity.MEDIUM,
            confidence=0.82,
            facts=facts,
            expected=values[0],
            actual=values[1],
            difference="value mismatch",
            suggestion="Confirm which value is authoritative and correct the other occurrences.",
        )
    ]


DETECTORS: dict[str, Callable[[ClaimCluster], list[Finding]]] = {
    "numeric": detect_numeric_conflicts,
    "date": detect_date_conflicts,
    "text": detect_text_conflicts,
}


def detect_conflicts(
    facts: list[Fact],
    *,
    cross_document_only: bool = False,
    enabled: set[str] | None = None,
) -> list[Finding]:
    """Cluster facts and run every registered conflict detector."""
    findings: list[Finding] = []
    for cluster in build_clusters(facts):
        if len(cluster.facts) < 2:
            continue
        if cross_document_only and not cluster.cross_document:
            continue
        for name, detector in DETECTORS.items():
            if enabled is not None and name not in enabled:
                continue
            findings.extend(detector(cluster))

    # Deduplicate: the same contradiction can surface from overlapping clusters.
    unique: dict[str, Finding] = {}
    for finding in findings:
        unique.setdefault(finding.fingerprint, finding)
    return list(unique.values())
