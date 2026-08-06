"""Post-generation evidence guard — reject hallucinated resume answers."""

from app.agents.contracts import NO_EVIDENCE
from app.core.config import get_settings

DEFAULT_NO_EVIDENCE = NO_EVIDENCE


def enforce_evidence_or_fallback(
    answer: str,
    evidence_spans: list[str],
) -> tuple[str, bool]:
    """Return (answer, has_evidence).

    If no evidence spans exist, never keep a fabricated answer.
    Force the configured fallback phrase (default: "No evidence found.").
    """
    settings = get_settings()
    fallback = settings.evidence_fallback or DEFAULT_NO_EVIDENCE
    cleaned = [span.strip() for span in evidence_spans if span and span.strip()]
    if not cleaned:
        return fallback, False
    if not answer or not answer.strip():
        return fallback, False
    # Model sometimes echoes the fallback even when spans exist.
    if answer.strip() in {fallback, DEFAULT_NO_EVIDENCE, "Not enough evidence found in resume."}:
        return fallback, False
    return answer.strip(), True


def fallback_phrase() -> str:
    return get_settings().evidence_fallback or DEFAULT_NO_EVIDENCE
