from __future__ import annotations

import re

from core.evidence import analyze_bullet, extract_evidence, metric_question
from core.models import RewriteProposal


LEADERSHIP_REQUEST_TERMS = (
    "led",
    "lead ",
    "managed",
    "supervised",
    "mentored",
    "team lead",
    "leadership",
)

LEADERSHIP_SOURCE_TERMS = (
    "led",
    "managed",
    "supervised",
    "mentored",
    "team lead",
    "direct reports",
)


def _clean(text: str) -> str:
    return " ".join(text.strip().split())


def _ensure_period(text: str) -> str:
    text = text.strip()

    if not text:
        return text

    if text[-1] not in ".!?":
        return text + "."

    return text


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def request_is_supported(
    source_bullet: str,
    requested_claim: str,
) -> tuple[bool, str]:
    """
    Check whether a requested claim is supported by the source bullet.

    This deliberately handles only claim families we can validate
    deterministically. Unsupported high-risk additions are rejected
    rather than guessed.
    """
    source = _clean(source_bullet)
    request = _clean(requested_claim)

    if not request:
        return True, "No additional claim requested."

    requests_leadership = _contains_any(
        request,
        LEADERSHIP_REQUEST_TERMS,
    )

    if requests_leadership:
        source_supports_leadership = _contains_any(
            source,
            LEADERSHIP_SOURCE_TERMS,
        )

        if not source_supports_leadership:
            return (
                False,
                "The requested leadership claim is not supported by "
                "the supplied resume evidence.",
            )

    return True, "Requested claim is supported by the supplied evidence."


def strengthen_structure(bullet: str) -> str:
    """
    Apply only conservative wording cleanup.

    No new facts, metrics, technologies, responsibilities,
    or outcomes are introduced here.
    """
    cleaned = _clean(bullet)

    replacements = (
        (
            r"(?i)^was responsible for processing\s+",
            "Processed ",
        ),
        (
            r"(?i)^responsible for processing\s+",
            "Processed ",
        ),
        (
            r"(?i)^was responsible for creating\s+",
            "Created ",
        ),
        (
            r"(?i)^responsible for creating\s+",
            "Created ",
        ),
        (
            r"(?i)^was responsible for developing\s+",
            "Developed ",
        ),
        (
            r"(?i)^responsible for developing\s+",
            "Developed ",
        ),
    )

    for pattern, replacement in replacements:
        if re.search(pattern, cleaned):
            cleaned = re.sub(
                pattern,
                replacement,
                cleaned,
                count=1,
            )
            break

    return _ensure_period(cleaned)


def _metric_to_result_clause(metric_text: str) -> str:
    """
    Convert a user-supplied result into a clause that can be appended
    without changing its factual content.
    """
    metric = _clean(metric_text).rstrip(".")

    conversions = (
        (r"(?i)^reduced\s+", "reducing "),
        (r"(?i)^saved\s+", "saving "),
        (r"(?i)^increased\s+", "increasing "),
        (r"(?i)^improved\s+", "improving "),
        (r"(?i)^decreased\s+", "decreasing "),
        (r"(?i)^cut\s+", "cutting "),
    )

    for pattern, replacement in conversions:
        if re.search(pattern, metric):
            return re.sub(
                pattern,
                replacement,
                metric,
                count=1,
            )

    if metric:
        return metric[0].lower() + metric[1:]

    return metric


def propose_rewrite(
    bullet: str,
    supplied_metric: str | None = None,
    requested_claim: str | None = None,
) -> RewriteProposal:
    """
    Produce an evidence-first rewrite proposal.

    Rules:
    1. Never invent quantitative impact.
    2. Never add unsupported leadership claims.
    3. User-supplied metrics must contain explicit quantitative evidence.
    4. All evidence used is returned for traceability.
    """
    source = _clean(bullet)

    if not source:
        return RewriteProposal(
            original_bullet="",
            proposed_bullet=None,
            status="unsupported",
            reason="A source bullet is required before a rewrite can be proposed.",
        )

    if requested_claim:
        supported, reason = request_is_supported(
            source,
            requested_claim,
        )

        if not supported:
            return RewriteProposal(
                original_bullet=source,
                proposed_bullet=None,
                status="unsupported",
                reason=reason,
            )

    source_analysis = analyze_bullet(source)
    evidence_used = [
        item.text
        for item in source_analysis.evidence
    ]

    metric = _clean(supplied_metric or "")

    if not source_analysis.has_quantified_evidence and not metric:
        return RewriteProposal(
            original_bullet=source,
            proposed_bullet=None,
            status="needs_metric",
            reason=(
                "The source bullet does not contain a measurable result. "
                "No metric will be invented."
            ),
            evidence_used=evidence_used,
            questions=[metric_question()],
        )

    if metric:
        metric_evidence = extract_evidence(metric)

        if not metric_evidence:
            return RewriteProposal(
                original_bullet=source,
                proposed_bullet=None,
                status="needs_metric",
                reason=(
                    "The supplied impact statement does not contain an "
                    "explicit measurable result."
                ),
                evidence_used=evidence_used,
                questions=[metric_question()],
            )

        evidence_used.extend(
            item.text
            for item in metric_evidence
        )

    rewritten = strengthen_structure(source).rstrip(".")

    if metric:
        metric_clause = _metric_to_result_clause(metric)

        if metric_clause.lower() not in rewritten.lower():
            rewritten = f"{rewritten}, {metric_clause}"

    rewritten = _ensure_period(rewritten)

    return RewriteProposal(
        original_bullet=source,
        proposed_bullet=rewritten,
        status="ready",
        reason=(
            "Rewrite uses only facts and measurable evidence supplied "
            "by the resume or the user."
        ),
        evidence_used=list(dict.fromkeys(evidence_used)),
    )