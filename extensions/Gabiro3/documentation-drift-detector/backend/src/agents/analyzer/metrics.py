"""Detection metrics for a run.

Ground truth, stated before the numbers
--------------------------------------
For a literal change fact (a rename or a changed default, e.g. npm -> pnpm
or 3000 -> 8080), a chunk genuinely contains that drift if and only if the
fact's `old_value` occurs in the chunk's text. That is decidable in code, so
it is used as ground truth: no human labelling, no model opinion.

A finding is therefore correct when it names a chunk that really does contain
the stale value — which is exactly "the Finder returned the right chunk id
AND the drift is actually located inside that chunk".

Limits, stated honestly
-----------------------
* This only works for literal facts. Reword-class drift has no literal
  `old_value` to search for, so those facts are excluded from scoring and
  reported separately rather than being silently counted as correct.
* Scores are computed over *committed* decisions only (CONFIRMED_DRIFT and
  NO_DRIFT). UNKNOWN is an abstention, reported as its own rate — counting an
  honest abstention as a miss would train the system to guess.
"""

import re
from dataclasses import asdict, dataclass, field

# Facts whose old_value is a literal string that must appear verbatim.
LITERAL_FACT_TYPES = {"renamed", "default_changed", "removed", "deprecated"}


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html(text)).strip().lower()


def chunk_contains(chunk_html: str, value: str) -> bool:
    """Whether a stale value genuinely occurs in a chunk, as a whole token.

    Plain substring matching is wrong here: 'npm' occurs inside 'pnpm', so a
    correctly-migrated doc reading 'pnpm install' would be scored as still
    containing the stale value. That would corrupt the ground truth itself
    and silently depress recall. Matches must therefore not be flanked by
    word characters or hyphens.
    """
    needle = normalize(value)
    if not needle:
        return False
    pattern = rf"(?<![\w-]){re.escape(needle)}(?![\w-])"
    return re.search(pattern, normalize(chunk_html)) is not None


@dataclass
class Metrics:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    accuracy: float | None = None

    committed: int = 0
    unknown: int = 0
    total_findings: int = 0
    coverage: float | None = None
    unknown_rate: float | None = None

    scored_facts: int = 0
    unscorable_facts: int = 0
    method: str = ""
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float | None:
    # None, not 0.0: "undefined" and "zero" are different claims.
    return round(numerator / denominator, 4) if denominator else None


def compute_metrics(
    change_facts: list[dict],
    chunks: list[dict],
    findings: list[dict],
) -> Metrics:
    """Score localization of literal drift.

    change_facts: {id, type, old_value}
    chunks:       {chunk_id, html}
    findings:     {change_fact_id, chunk_id, evidence_chunk_id, state}
    """
    m = Metrics()
    m.method = (
        "A chunk is ground-truth positive for a literal change fact when the "
        "fact's old_value occurs in the chunk text. TP = a CONFIRMED finding "
        "naming such a chunk. Scored over committed decisions only; UNKNOWN "
        "is reported separately."
    )

    m.total_findings = len(findings)
    committed = [f for f in findings if f.get("state") in ("CONFIRMED_DRIFT", "NO_DRIFT")]
    m.committed = len(committed)
    m.unknown = sum(1 for f in findings if f.get("state") == "UNKNOWN")
    m.coverage = _ratio(m.committed, m.total_findings)
    m.unknown_rate = _ratio(m.unknown, m.total_findings)

    all_chunk_ids = {c["chunk_id"] for c in chunks}
    multi_chunk_facts = 0

    for fact in change_facts:
        fact_id = str(fact.get("id"))
        old_value = (fact.get("old_value") or "").strip()
        is_literal = fact.get("type") in LITERAL_FACT_TYPES and bool(old_value)

        if not is_literal:
            m.unscorable_facts += 1
            continue
        m.scored_facts += 1

        relevant = {
            c["chunk_id"] for c in chunks if chunk_contains(c.get("html", ""), old_value)
        }

        predicted = {
            (f.get("evidence_chunk_id") or f.get("chunk_id"))
            for f in committed
            if f.get("state") == "CONFIRMED_DRIFT"
            and str(f.get("change_fact_id")) == fact_id
        }
        predicted.discard(None)
        predicted.discard("")

        if len(relevant) > 1 and len(predicted) <= 1:
            multi_chunk_facts += 1

        tp = len(predicted & relevant)
        fp = len(predicted - relevant)
        fn = len(relevant - predicted)
        tn = len(all_chunk_ids - (predicted | relevant))

        m.true_positives += tp
        m.false_positives += fp
        m.false_negatives += fn
        m.true_negatives += tn

    if multi_chunk_facts:
        # The Finder emits one finding per drifted chunk, so this is no longer
        # a scoring artefact — it is genuine under-detection and is counted
        # against recall accordingly.
        m.limitations.append(
            f"{multi_chunk_facts} change fact(s) were flagged in only one chunk "
            f"despite being present in several. These are real misses, not a "
            f"scoring artefact, and are counted as false negatives."
        )

    m.precision = _ratio(m.true_positives, m.true_positives + m.false_positives)
    m.recall = _ratio(m.true_positives, m.true_positives + m.false_negatives)
    if m.precision is not None and m.recall is not None and (m.precision + m.recall):
        m.f1 = round(2 * m.precision * m.recall / (m.precision + m.recall), 4)
    m.accuracy = _ratio(
        m.true_positives + m.true_negatives,
        m.true_positives + m.true_negatives + m.false_positives + m.false_negatives,
    )

    if m.unscorable_facts:
        m.limitations.append(
            f"{m.unscorable_facts} non-literal change fact(s) excluded: no "
            f"verbatim old_value to locate, so correctness is not decidable in code."
        )
    if m.unknown:
        m.limitations.append(
            f"{m.unknown} UNKNOWN finding(s) excluded from precision/recall; "
            f"see unknown_rate. Abstentions are not counted as misses."
        )
    if not m.scored_facts:
        m.limitations.append("No literal change facts in this run; scores are undefined.")

    return m
