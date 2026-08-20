"""Fact extraction: deterministic first, LLM as an additive enrichment.

Why this order? Regex/parser extraction is free, reproducible and citable by
construction — every fact points at the exact block and character span it came
from. The LLM then adds what patterns cannot see (obligations, deliverables,
parties, semantic labels for numbers), but each LLM fact must quote verbatim
text that is verified to exist in the document before it is kept. Unverifiable
LLM output is discarded, not surfaced — hallucinated facts are worse than
missing ones in an audit tool.
"""

from __future__ import annotations

import re
from uuid import UUID

from app.core.errors import LLMError, LLMUnavailable
from app.core.logging import get_logger
from app.engines.normalization import (
    DATE_RE,
    MONEY_RE,
    NUMBER_RE,
    PERCENT_RE,
    parse_date,
    parse_money,
    parse_percentage,
    to_decimal,
)
from app.schemas.domain import Fact, FactType, ParsedDocument, TextBlock
from app.services.llm import LLMClient, Usage

log = get_logger(__name__)

# Label inference: the words immediately before a value usually name it.
_LABEL_WINDOW = 60

_METRIC_KEYWORDS: tuple[tuple[str, FactType], ...] = (
    ("revenue", FactType.REVENUE),
    ("turnover", FactType.REVENUE),
    ("net income", FactType.NET_INCOME),
    ("net profit", FactType.PROFIT),
    ("gross profit", FactType.PROFIT),
    ("profit", FactType.PROFIT),
    ("expense", FactType.EXPENSE),
    ("cost", FactType.EXPENSE),
    ("tax", FactType.TAX),
    ("gst", FactType.TAX),
    ("vat", FactType.TAX),
)

_DEADLINE_RE = re.compile(r"\b(due|deadline|expiry|expires?|no later than|by)\b", re.I)
_INVOICE_NO_RE = re.compile(r"\binvoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})", re.I)
_GST_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_COMPANY_RE = re.compile(
    r"\b([A-Z][\w&.,'-]*(?:\s+[A-Z][\w&.,'-]*){0,4}\s+(?:Inc|LLC|Ltd|Limited|Pvt|GmbH|PLC|Corp|Corporation|Company|LLP)\b\.?)"
)
_PERSON_RE = re.compile(r"\b(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
_OBLIGATION_RE = re.compile(
    r"\b(shall|must|is required to|agrees to|will deliver|undertakes to)\b", re.I
)


def _label_for(text: str, start: int) -> str:
    """Take the phrase preceding a value as its label."""
    left = text[max(0, start - _LABEL_WINDOW) : start]
    left = re.split(r"[.;\n]", left)[-1]
    left = re.sub(r"[^\w %/&().-]+", " ", left)
    words = [w for w in left.split() if w]
    label = " ".join(words[-6:]).strip(" :-–—|")
    return label[:200]


def _metric_type(label: str, default: FactType) -> FactType:
    lowered = label.lower()
    for keyword, fact_type in _METRIC_KEYWORDS:
        if keyword in lowered:
            return fact_type
    return default


def _fact(
    block: TextBlock,
    *,
    document_id: UUID | None,
    fact_type: FactType,
    label: str,
    raw_value: str,
    normalized: dict,
    match_start: int,
    match_end: int,
    confidence: float,
    unit: str | None = None,
) -> Fact:
    char_start = block.char_start + match_start
    return Fact(
        document_id=document_id,
        fact_type=fact_type,
        label=label or fact_type.value,
        raw_value=raw_value.strip(),
        normalized_value=normalized,
        unit=unit,
        confidence=confidence,
        extractor="deterministic",
        page=block.page,
        section=block.section,
        paragraph=block.paragraph,
        char_start=char_start,
        char_end=block.char_start + match_end,
        citation=block.citation(document_id=document_id, quote=block.text),
    )


def extract_from_block(block: TextBlock, document_id: UUID | None = None) -> list[Fact]:
    """All deterministic patterns applied to a single block."""
    text = block.text
    facts: list[Fact] = []
    consumed: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < e and end > s for s, e in consumed)

    if block.kind == "heading":
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=FactType.HEADING,
                label="section",
                raw_value=text,
                normalized={"heading": text},
                match_start=0,
                match_end=len(text),
                confidence=0.95,
            )
        )

    for match in MONEY_RE.finditer(text):
        parsed = parse_money(match.group(0))
        if not parsed:
            continue
        label = _label_for(text, match.start())
        fact_type = _metric_type(label, FactType.CURRENCY)
        consumed.append((match.start(), match.end()))
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=fact_type,
                label=label,
                raw_value=match.group(0),
                normalized=parsed,
                match_start=match.start(),
                match_end=match.end(),
                confidence=0.9 if label else 0.75,
                unit=parsed.get("currency"),
            )
        )

    for match in PERCENT_RE.finditer(text):
        parsed = parse_percentage(match.group(0))
        if not parsed:
            continue
        consumed.append((match.start(), match.end()))
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=FactType.PERCENTAGE,
                label=_label_for(text, match.start()),
                raw_value=match.group(0),
                normalized=parsed,
                match_start=match.start(),
                match_end=match.end(),
                confidence=0.88,
                unit="%",
            )
        )

    for match in DATE_RE.finditer(text):
        parsed = parse_date(match.group(0))
        if not parsed:
            continue
        consumed.append((match.start(), match.end()))
        label = _label_for(text, match.start())
        is_deadline = bool(_DEADLINE_RE.search(label) or _DEADLINE_RE.search(text[:80]))
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=FactType.DEADLINE if is_deadline else FactType.DATE,
                label=label,
                raw_value=match.group(0),
                normalized=parsed,
                match_start=match.start(),
                match_end=match.end(),
                confidence=0.7 if parsed.get("ambiguous") else 0.92,
            )
        )

    for pattern, fact_type, confidence in (
        (_INVOICE_NO_RE, FactType.INVOICE_NUMBER, 0.95),
        (_GST_RE, FactType.GST_NUMBER, 0.95),
        (_COMPANY_RE, FactType.COMPANY, 0.7),
        (_PERSON_RE, FactType.PERSON, 0.75),
    ):
        for match in pattern.finditer(text):
            value = match.group(1) if match.groups() else match.group(0)
            if overlaps(match.start(), match.end()):
                continue
            facts.append(
                _fact(
                    block,
                    document_id=document_id,
                    fact_type=fact_type,
                    label=fact_type.value,
                    raw_value=value,
                    normalized={"value": value},
                    match_start=match.start(),
                    match_end=match.end(),
                    confidence=confidence,
                )
            )

    for match in _EMAIL_RE.finditer(text):
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=FactType.PERSON,
                label="email",
                raw_value=match.group(0),
                normalized={"email": match.group(0)},
                match_start=match.start(),
                match_end=match.end(),
                confidence=0.9,
            )
        )

    if _OBLIGATION_RE.search(text) and len(text) > 30:
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=FactType.OBLIGATION,
                label=(block.section or "obligation")[:200],
                raw_value=text[:500],
                normalized={"statement": text[:1000]},
                match_start=0,
                match_end=len(text),
                confidence=0.65,
            )
        )

    # Bare numbers: only when they carry a label, otherwise they are noise.
    for match in NUMBER_RE.finditer(text):
        if overlaps(match.start(), match.end()):
            continue
        label = _label_for(text, match.start())
        if not label or len(label) < 3:
            continue
        value = to_decimal(match.group(0))
        if value is None:
            continue
        facts.append(
            _fact(
                block,
                document_id=document_id,
                fact_type=_metric_type(label, FactType.NUMBER),
                label=label,
                raw_value=match.group(0),
                normalized={"value": float(value)},
                match_start=match.start(),
                match_end=match.end(),
                confidence=0.6,
            )
        )

    return facts


def extract_from_tables(parsed: ParsedDocument, document_id: UUID | None = None) -> list[Fact]:
    """One fact per table so downstream arithmetic keeps the structure."""
    facts: list[Fact] = []
    for index, table in enumerate(parsed.tables):
        facts.append(
            Fact(
                document_id=document_id,
                fact_type=FactType.TABLE,
                label=table.caption or f"table_{index + 1}",
                raw_value=" | ".join(table.header)[:500],
                normalized_value={
                    "header": table.header,
                    "rows": table.rows,
                    "index": index,
                },
                confidence=0.9,
                extractor="deterministic",
                page=table.page,
                section=table.section,
            )
        )
    return facts


def deduplicate(facts: list[Fact]) -> list[Fact]:
    seen: dict[str, Fact] = {}
    for fact in facts:
        existing = seen.get(fact.dedupe_key)
        if existing is None or fact.confidence > existing.confidence:
            seen[fact.dedupe_key] = fact
    return list(seen.values())


def extract_deterministic(parsed: ParsedDocument, document_id: UUID | None = None) -> list[Fact]:
    facts: list[Fact] = []
    for block in parsed.blocks:
        facts.extend(extract_from_block(block, document_id=document_id))
    facts.extend(extract_from_tables(parsed, document_id=document_id))
    return deduplicate(facts)


LLM_EXTRACTION_PROMPT = """Extract structured facts from the document below.
Return JSON: {"facts": [{"fact_type": one of person|company|address|date|currency|percentage|financial_metric|obligation|deliverable|deadline,
"label": short name, "value": the value as written, "quote": VERBATIM sentence from the document containing the value, "confidence": 0-1}]}
Rules: the quote must appear character-for-character in the document. Do not
infer values that are absent. Maximum 40 facts, prioritise obligations,
deliverables, parties and labelled financial metrics."""


def _find_block(parsed: ParsedDocument, quote: str) -> TextBlock | None:
    needle = " ".join(quote.split()).lower()
    if len(needle) < 12:
        return None
    for block in parsed.blocks:
        if needle in " ".join(block.text.split()).lower():
            return block
    return None


def extract_with_llm(
    parsed: ParsedDocument,
    llm: LLMClient,
    *,
    document_id: UUID | None = None,
    max_chars: int = 12_000,
) -> tuple[list[Fact], Usage]:
    """LLM enrichment. Facts whose quote cannot be located are dropped."""
    usage = Usage()
    if not llm.enabled or not parsed.text.strip():
        return [], usage

    try:
        completion = llm.complete(LLM_EXTRACTION_PROMPT, untrusted=parsed.text[:max_chars])
    except (LLMUnavailable, LLMError) as exc:
        log.info("llm_extraction_degraded", reason=str(exc))
        return [], usage

    usage.add(completion.usage)
    payload = completion.json({}) or {}
    facts: list[Fact] = []
    dropped = 0

    for item in (payload.get("facts") or [])[:40]:
        try:
            fact_type = FactType(str(item.get("fact_type", "")).lower())
        except ValueError:
            dropped += 1
            continue
        quote = str(item.get("quote") or "")
        block = _find_block(parsed, quote)
        if block is None:
            dropped += 1  # unverifiable => hallucination risk => discard
            continue
        value = str(item.get("value") or "")
        normalized = (
            parse_money(value)
            or parse_percentage(value)
            or parse_date(value)
            or {"value": value}
        )
        facts.append(
            Fact(
                document_id=document_id,
                fact_type=fact_type,
                label=str(item.get("label") or fact_type.value)[:200],
                raw_value=value[:500],
                normalized_value=normalized,
                confidence=min(float(item.get("confidence", 0.6) or 0.6), 0.9),
                extractor="llm",
                page=block.page,
                section=block.section,
                paragraph=block.paragraph,
                char_start=block.char_start,
                char_end=block.char_end,
                citation=block.citation(document_id=document_id, quote=quote or block.text),
            )
        )

    if dropped:
        log.info("llm_facts_dropped", dropped=dropped, kept=len(facts))
    return facts, usage


def extract_facts(
    parsed: ParsedDocument,
    *,
    document_id: UUID | None = None,
    llm: LLMClient | None = None,
) -> tuple[list[Fact], Usage]:
    """Full extraction pipeline: deterministic ∪ verified LLM facts."""
    facts = extract_deterministic(parsed, document_id=document_id)
    usage = Usage()
    if llm is not None and llm.enabled:
        llm_facts, llm_usage = extract_with_llm(parsed, llm, document_id=document_id)
        usage.add(llm_usage)
        facts = deduplicate(facts + llm_facts)
    return facts, usage
