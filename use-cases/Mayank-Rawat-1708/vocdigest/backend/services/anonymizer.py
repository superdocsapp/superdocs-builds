"""
@file: backend/services/anonymizer.py
@description: Quote anonymization. Runs a deterministic regex pass for the categories
    that have reliable shapes (email, phone, ticket/account ids, URLs), then optionally
    an LLM pass for the context-dependent ones (person names, company names). Anything
    the LLM is unsure about becomes [POSSIBLE-NAME] rather than being silently redacted
    or silently passed through — the uncertainty is the output, not a hidden decision.
@flow: anonymize_quote(text) -> regex pass produces redactions with high confidence ->
    LLM pass proposes name/company spans with a confidence each -> spans above the
    certain threshold become [USER]/[COMPANY], spans below become [POSSIBLE-NAME] ->
    AnonymizedQuote carries the result plus every redaction made, for human review.
@dependencies:
    - re: deterministic pattern pass
    - backend.services.groq_client.GroqClient: context-aware pass (optional)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.services.groq_client import GroqClient, LLMUsage

logger = logging.getLogger(__name__)

# Confidence at or above which we assert a redaction outright. Below it we mark the span
# [POSSIBLE-NAME] and let a human decide at the gate.
CERTAIN_THRESHOLD = 0.85

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Deliberately conservative: broad phone regexes eat order numbers and version strings.
_PHONE = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\w)"
)
_TICKET = re.compile(
    r"\b(?:ticket|case|acct|account|ref|order|invoice|sub)[\s#:_-]*([A-Z0-9][A-Z0-9-]{3,})\b",
    re.IGNORECASE,
)
_UUIDISH = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_URL = re.compile(r"https?://[^\s<>\"']+")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_REGEX_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (_EMAIL, "[EMAIL]", "email"),
    (_URL, "[URL]", "url"),
    (_CARD, "[REDACTED-NUMBER]", "card_like"),
    (_PHONE, "[PHONE]", "phone"),
    (_UUIDISH, "[ID]", "uuid"),
    (_TICKET, "[ID]", "ticket_id"),
]


@dataclass(slots=True)
class Redaction:
    """One replacement made, kept so a reviewer can audit what was removed."""

    original: str
    replacement: str
    category: str
    confidence: float
    method: str  # "regex" | "llm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "replacement": self.replacement,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


@dataclass(slots=True)
class AnonymizedQuote:
    """Result of anonymizing one quote."""

    original: str
    anonymized: str
    redactions: list[Redaction] = field(default_factory=list)
    uncertain_spans: list[str] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)

    @property
    def has_uncertainty(self) -> bool:
        return bool(self.uncertain_spans)

    @property
    def needs_review(self) -> bool:
        """True when a human should look before this quote ships.

        Uncertain spans always need review. So does a quote where nothing at all was
        redacted but the text contains a capitalised token that could be a name we
        missed — better to over-surface than to leak.
        """
        return self.has_uncertainty

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "anonymized": self.anonymized,
            "redactions": [r.to_dict() for r in self.redactions],
            "uncertain_spans": self.uncertain_spans,
            "needs_review": self.needs_review,
        }


# Capitalised tokens that are not sentence-initial and not obviously a product term.
# Used as a pre-screen: if a quote contains none of these, there is nothing for the name
# detector to find and the LLM call is pure waste. Deliberately generous — it decides
# whether to *ask*, so a false positive costs one call and a false negative costs a leak.
_NAME_CANDIDATE = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)

# Words that are capitalised in support text but are never personal names. Keeping this
# list short on purpose: over-filtering here turns into missed redactions.
_NEVER_NAMES = {
    "Export", "Dashboard", "Notification", "Notifications", "Billing", "Mobile",
    "Android", "Windows", "Chrome", "Safari", "Firefox", "Excel", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
    "March", "April", "June", "July", "August", "September", "October", "November",
    "December", "Please", "Thanks", "Thank", "This", "That", "There", "When", "What",
    "Why", "How", "Also", "Every", "Since", "After", "Before", "None", "Hello",
}


def has_name_candidate(text: str) -> bool:
    """Whether a quote plausibly contains a personal or company name.

    Lets the anonymizer skip the LLM pass for the majority of quotes, which mention no
    names at all, without weakening coverage for the ones that do.
    """
    return any(
        token not in _NEVER_NAMES for token in _NAME_CANDIDATE.findall(text)
    )


_LLM_SYSTEM = """\
You identify personal and company identifiers in support-conversation text so they can
be removed before publication.

Return ONLY a valid JSON object with this exact shape:
{
  "spans": [
    {"text": "<exact substring from the input>",
     "category": "person" | "company" | "other",
     "confidence": <float 0.0-1.0>}
  ]
}

Rules:
- "text" MUST be an exact substring of the input, copied verbatim.
- Use confidence honestly. A clearly-addressed human name in a greeting is high
  confidence. A capitalised word that might be a product, a place, or a name is low
  confidence. Do not round low confidence up.
- Do NOT list product names, feature names, generic role words ("the admin", "support"),
  or common nouns.
- If you find nothing, return {"spans": []}. Never invent a span to seem useful.
"""


_BATCH_LLM_SYSTEM = """\
You identify personal and company identifiers in support-conversation quotes so they can
be removed before publication.

Each quote is prefixed with an index like [0], [1]. Return ONLY a valid JSON object:
{
  "results": [
    {"index": <int>,
     "spans": [{"text": "<exact substring>", "category": "person"|"company"|"other",
                "confidence": <float 0.0-1.0>}]}
  ]
}

Rules:
- "text" MUST be an exact substring of that quote, copied verbatim.
- Include an entry for EVERY index you were given, with an empty spans list if the quote
  contains no identifiers.
- Use confidence honestly. A name in a greeting is high confidence. A capitalised word
  that might be a product, a place, or a name is low confidence. Do not round up.
- Do NOT list product names, feature names, generic role words, or common nouns.
"""


class Anonymizer:
    """Two-pass anonymizer: deterministic regex, then optional LLM for names.

    The LLM pass is optional so the whole pipeline still runs (with reduced name
    coverage, honestly reported) when Groq is unavailable.
    """

    def __init__(self, groq: GroqClient | None = None) -> None:
        self._groq = groq

    def anonymize_regex_only(self, text: str) -> AnonymizedQuote:
        """Deterministic pass. Same input always yields the same output."""
        working = text
        redactions: list[Redaction] = []

        for pattern, replacement, category in _REGEX_RULES:
            for match in list(pattern.finditer(working)):
                original = match.group(0)
                if original in {r.original for r in redactions}:
                    continue
                redactions.append(
                    Redaction(
                        original=original,
                        replacement=replacement,
                        category=category,
                        confidence=0.97,
                        method="regex",
                    )
                )
            working = pattern.sub(replacement, working)

        return AnonymizedQuote(
            original=text, anonymized=working, redactions=redactions
        )

    async def anonymize(self, text: str, *, use_llm: bool = True) -> AnonymizedQuote:
        """Full anonymization. Falls back to regex-only if the LLM pass fails."""
        result = self.anonymize_regex_only(text)

        if not use_llm or self._groq is None:
            # Pattern-only result. Flag it so a reviewer knows name coverage was not
            # attempted, rather than assuming a clean pass meant no names were present.
            result.uncertain_spans.append(
                "name detection not run (no language model available)"
            )
            return result

        try:
            payload, usage, _ = await self._groq.complete_json(
                _LLM_SYSTEM,
                "Identify person and company identifiers in the text below.",
                untrusted_content=result.anonymized,
                max_tokens=1024,
            )
            result.usage.merge(usage)
        except Exception as exc:
            # Degrade honestly: keep the regex result and record that name coverage is
            # reduced, rather than pretending the quote is fully anonymized.
            logger.warning("LLM anonymization pass failed, regex-only result: %s", exc)
            result.uncertain_spans.append(
                "LLM name detection unavailable — names may remain"
            )
            return result

        spans = payload.get("spans", []) if isinstance(payload, dict) else []
        self._apply_spans(result, spans)
        return result

    async def anonymize_many(
        self, texts: list[str], *, use_llm: bool = True
    ) -> list[AnonymizedQuote]:
        """Anonymize a group of quotes using ONE LLM call for the whole group.

        Replaces a per-quote loop that made one request each — on a 200-conversation run
        that was ~144 sequential calls, minutes of wall clock, and the bulk of the token
        spend. Two changes fix it: quotes with no name-shaped token skip the LLM pass
        entirely (most quotes), and the remainder are sent together.
        """
        results = [self.anonymize_regex_only(t) for t in texts]

        if not use_llm or self._groq is None:
            for result in results:
                result.uncertain_spans.append(
                    "name detection not run (no language model available)"
                )
            return results

        # Only quotes that could contain a name need the model.
        needs_llm = [
            (i, r) for i, r in enumerate(results) if has_name_candidate(r.anonymized)
        ]
        if not needs_llm:
            return results

        # Respect the run-level breaker: if the allowance is already known to be spent,
        # do not make a call that is certain to 429.
        from backend.services.llm_gate import breaker_is_open, trip_breaker

        if breaker_is_open():
            for _, result in needs_llm:
                result.uncertain_spans.append(
                    "LLM name detection unavailable (token allowance exhausted)"
                )
            return results

        numbered = "\n\n".join(f"[{i}] {r.anonymized}" for i, r in needs_llm)
        try:
            payload, usage, _ = await self._groq.complete_json(
                _BATCH_LLM_SYSTEM,
                f"Identify person and company identifiers in these {len(needs_llm)} quotes.",
                untrusted_content=numbered,
                max_tokens=min(512 + 256 * len(needs_llm), 4096),
            )
            results[0].usage.merge(usage)  # attributed to the group
        except Exception as exc:
            from backend.services.groq_client import GroqQuotaExhausted

            if isinstance(exc, GroqQuotaExhausted):
                # Every remaining theme would fail identically. Trip the breaker so this
                # is discovered once rather than once per theme.
                trip_breaker(str(exc), getattr(exc, "retry_after_s", None))
                note = "LLM name detection unavailable (token allowance exhausted)"
            else:
                note = "LLM name detection unavailable — names may remain"
            logger.warning("Batched LLM anonymization failed, regex-only: %s", exc)
            for _, result in needs_llm:
                result.uncertain_spans.append(note)
            return results

        by_quote: dict[int, list[dict]] = {}
        if isinstance(payload, dict):
            for item in payload.get("results", []) or []:
                try:
                    by_quote.setdefault(int(item["index"]), []).extend(
                        item.get("spans", []) or []
                    )
                except (KeyError, TypeError, ValueError):
                    continue

        for index, result in needs_llm:
            spans = by_quote.get(index)
            if spans is None:
                # The model skipped this quote. Say so rather than treating silence as
                # "no names found", which would be an unearned clean bill of health.
                result.uncertain_spans.append(
                    "model returned no name analysis for this quote"
                )
                continue
            self._apply_spans(result, spans)

        return results

    def _apply_spans(self, result: AnonymizedQuote, spans: list[dict]) -> None:
        """Apply model-proposed name spans to one quote.

        Shared by the single and batched paths so both resolve confidence the same way —
        above threshold becomes a definite redaction, below becomes [POSSIBLE-NAME].
        """
        working = result.anonymized
        # Longest first so a full name is replaced before its component parts.
        for span in sorted(spans, key=lambda s: len(str(s.get("text", ""))), reverse=True):
            raw = str(span.get("text", "")).strip()
            if not raw or raw not in working:
                continue
            category = str(span.get("category", "other")).lower()
            try:
                confidence = float(span.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            if confidence >= CERTAIN_THRESHOLD:
                replacement = {"person": "[USER]", "company": "[COMPANY]"}.get(
                    category, "[REDACTED]"
                )
            else:
                replacement = "[POSSIBLE-NAME]"
                result.uncertain_spans.append(raw)

            working = working.replace(raw, replacement)
            result.redactions.append(
                Redaction(
                    original=raw,
                    replacement=replacement,
                    category=category,
                    confidence=confidence,
                    method="llm",
                )
            )
        result.anonymized = working