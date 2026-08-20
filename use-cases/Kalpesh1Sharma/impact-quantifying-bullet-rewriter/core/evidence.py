import re

from core.models import BulletAnalysis, EvidenceItem


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "percentage",
        re.compile(r"\b\d+(?:\.\d+)?\s*%"),
    ),
    (
        "currency",
        re.compile(
            r"(?:₹|\$|€|£)\s?\d[\d,]*(?:\.\d+)?"
            r"|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|INR|EUR|GBP)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "duration",
        re.compile(
            r"\b\d+(?:\.\d+)?\s*"
            r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "volume",
        re.compile(
            r"\b\d[\d,]*(?:\.\d+)?\s+"
            r"(?:"
            r"invoices?|records?|reports?|files?|documents?|tickets?|"
            r"customers?|clients?|users?|transactions?|orders?|requests?|"
            r"dashboards?|pipelines?|models?|queries?|jobs?|cases?"
            r")\b",
            re.IGNORECASE,
        ),
    ),
]


def _overlaps(
    start: int,
    end: int,
    occupied: list[tuple[int, int]],
) -> bool:
    return any(start < existing_end and end > existing_start for existing_start, existing_end in occupied)


def extract_evidence(text: str) -> list[EvidenceItem]:
    """
    Extract explicit quantitative evidence from a resume bullet.

    Important:
    This function only detects evidence that is literally present
    in the supplied text. It never infers or invents metrics.
    """
    if not text or not text.strip():
        return []

    evidence: list[EvidenceItem] = []
    occupied: list[tuple[int, int]] = []

    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()

            if _overlaps(start, end, occupied):
                continue

            evidence.append(
                EvidenceItem(
                    text=match.group(0),
                    kind=kind,  # type: ignore[arg-type]
                    start=start,
                    end=end,
                )
            )
            occupied.append((start, end))

    evidence.sort(key=lambda item: item.start)
    return evidence


def analyze_bullet(text: str) -> BulletAnalysis:
    cleaned = text.strip()
    evidence = extract_evidence(cleaned)

    missing: list[str] = []

    if not evidence:
        missing.append("quantified impact")

    return BulletAnalysis(
        original_bullet=cleaned,
        evidence=evidence,
        has_quantified_evidence=bool(evidence),
        missing_evidence=missing,
    )


def metric_question() -> str:
    return (
        "Do you know a measurable result for this work, such as time saved, "
        "processing-time reduction, volume handled, error reduction, "
        "revenue generated, or cost saved?"
    )