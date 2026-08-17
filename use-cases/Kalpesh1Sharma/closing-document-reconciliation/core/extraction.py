from __future__ import annotations

from typing import Any

from core.models import (
    DocumentType,
    ExtractedMortgageDocument,
    FieldEvidence,
    FileRule,
)
from core.normalize import (
    normalize_boolean,
    normalize_money,
    normalize_percentage,
    normalize_term_months,
)


def _evidence(
    *,
    data: dict[str, Any] | None,
    source_document: str,
    normalizer=None,
) -> FieldEvidence:
    data = data or {}

    raw_value = data.get("raw_value")
    quote = data.get("supporting_quote")

    normalized_value = (
        normalizer(raw_value)
        if normalizer is not None
        else raw_value
    )

    return FieldEvidence(
        value=normalized_value,
        raw_value=raw_value,
        supporting_quote=quote,
        source_document=source_document,
    )


def build_extracted_document(
    *,
    filename: str,
    raw: dict[str, Any],
) -> ExtractedMortgageDocument:
    try:
        document_type = DocumentType(
            raw.get("document_type", "unknown")
        )
    except ValueError:
        document_type = DocumentType.UNKNOWN

    fees = raw.get("fees") or {}

    extracted_rules = []

    for rule in raw.get("rules") or []:
        rule_id = rule.get("rule_id")
        rule_text = rule.get("rule_text")
        supporting_quote = rule.get("supporting_quote")

        if not rule_id or not rule_text or not supporting_quote:
            continue

        extracted_rules.append(
            FileRule(
                rule_id=rule_id,
                rule_text=rule_text,
                source_document=filename,
                supporting_quote=supporting_quote,
            )
        )

    return ExtractedMortgageDocument(
        document_type=document_type,
        filename=filename,

        borrower_names=_evidence(
            data=raw.get("borrower_names"),
            source_document=filename,
        ),

        property_address=_evidence(
            data=raw.get("property_address"),
            source_document=filename,
        ),

        loan_amount=_evidence(
            data=raw.get("loan_amount"),
            source_document=filename,
            normalizer=normalize_money,
        ),

        interest_rate=_evidence(
            data=raw.get("interest_rate"),
            source_document=filename,
            normalizer=normalize_percentage,
        ),

        term_months=_evidence(
            data=raw.get("term"),
            source_document=filename,
            normalizer=normalize_term_months,
        ),

        escrow=_evidence(
            data=raw.get("escrow"),
            source_document=filename,
            normalizer=normalize_boolean,
        ),

        fees={
            "origination": _evidence(
                data=fees.get("origination"),
                source_document=filename,
                normalizer=normalize_money,
            ),
            "title_services": _evidence(
                data=fees.get("title_services"),
                source_document=filename,
                normalizer=normalize_money,
            ),
        },

        cash_to_close=_evidence(
            data=raw.get("cash_to_close"),
            source_document=filename,
            normalizer=normalize_money,
        ),
        rules=extracted_rules,
    )