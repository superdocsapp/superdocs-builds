from __future__ import annotations

import json
import re
from typing import Any


class SuperDocsParseError(ValueError):
    pass


def parse_json_response(text: str) -> dict[str, Any]:
    """
    Parse a JSON object from a SuperDocs response.

    Supports:
    - pure JSON
    - accidental Markdown fences
    - prose before a valid JSON object
    """

    if not text or not text.strip():
        raise SuperDocsParseError(
            "SuperDocs returned an empty response."
        )

    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)

        if not isinstance(parsed, dict):
            raise SuperDocsParseError(
                "Expected a JSON object from SuperDocs."
            )

        return parsed

    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()

    for index, character in enumerate(cleaned):
        if character != "{":
            continue

        try:
            parsed, _ = decoder.raw_decode(
                cleaned[index:]
            )
        except json.JSONDecodeError:
            continue

        if isinstance(parsed, dict):
            return parsed

    raise SuperDocsParseError(
        "No valid JSON object was found in the SuperDocs response."
    )


def _empty_extraction(
    document_type: str,
) -> dict[str, Any]:
    return {
        "document_type": document_type,

        "borrower_names": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "property_address": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "loan_amount": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "interest_rate": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "term": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "escrow": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "fees": {
            "origination": {
                "raw_value": None,
                "supporting_quote": None,
            },

            "title_services": {
                "raw_value": None,
                "supporting_quote": None,
            },
        },

        "cash_to_close": {
            "raw_value": None,
            "supporting_quote": None,
        },

        "rules": [],
    }


def parse_bullet_extraction(
    text: str,
    *,
    expected_document_type: str,
) -> dict[str, Any]:
    """
    Deterministic fallback for a common SuperDocs behavior:

        * **Loan Amount**: $420,000.00
        * **Interest Rate**: 6.625%

    This parser extracts ONLY values explicitly present in those
    bullet lines. It does not infer missing values.
    """

    if not text or not text.strip():
        raise SuperDocsParseError(
            "Cannot parse an empty bullet response."
        )

    extraction = _empty_extraction(
        expected_document_type
    )

    aliases = {
        "borrowers": ("borrower_names", None),
        "borrower": ("borrower_names", None),
        "applicants": ("borrower_names", None),

        "property address": ("property_address", None),
        "property": ("property_address", None),
        "property location": ("property_address", None),

        "loan amount": ("loan_amount", None),
        "amount of loan": ("loan_amount", None),
        "principal sum": ("loan_amount", None),
        "approved principal": ("loan_amount", None),

        "interest rate": ("interest_rate", None),
        "interest": ("interest_rate", None),
        "approved note rate": ("interest_rate", None),

        "loan term": ("term", None),
        "term": ("term", None),
        "maturity": ("term", None),
        "amortization term": ("term", None),

        "escrow property costs": ("escrow", None),
        "escrow account": ("escrow", None),
        "escrow requirement": ("escrow", None),
        "escrow collected": ("escrow", None),

        "origination charges": ("fees", "origination"),
        "loan costs — origination": ("fees", "origination"),
        "loan costs - origination": ("fees", "origination"),

        "title services": ("fees", "title_services"),
        "title & settlement services": ("fees", "title_services"),
        "settlement / title charges": ("fees", "title_services"),

        "cash to close": ("cash_to_close", None),
        "estimated cash to close": ("cash_to_close", None),
        "amount due from borrower": ("cash_to_close", None),
    }

    matched_fields = 0

    pattern = re.compile(
        r"^\s*[*-]\s*\*\*(.+?)\*\*\s*:\s*(.+?)\s*$"
    )

    for raw_line in text.splitlines():
        match = pattern.match(raw_line)

        if not match:
            continue

        label = match.group(1).strip()
        value = match.group(2).strip()

        normalized_label = re.sub(
            r"\s+",
            " ",
            label.lower(),
        )

        target = aliases.get(
            normalized_label
        )

        if target is None:
            continue

        field_name, nested_name = target

        # Preserve a readable evidence line from the response.
        quote = f"{label}: {value}"

        if field_name == "fees":
            extraction["fees"][nested_name] = {
                "raw_value": value,
                "supporting_quote": quote,
            }
        else:
            extraction[field_name] = {
                "raw_value": value,
                "supporting_quote": quote,
            }

        matched_fields += 1

    if matched_fields == 0:
        raise SuperDocsParseError(
            "Response was neither valid JSON nor a recognized "
            "structured bullet extraction."
        )

    return extraction


def parse_extraction_response(
    text: str,
    *,
    expected_document_type: str,
) -> dict[str, Any]:
    """
    Primary parser used for mortgage extraction.

    Strategy:
    1. Strict JSON first.
    2. Deterministic structured-bullet fallback.
    3. Fail rather than guess.
    """

    try:
        return parse_json_response(
            text
        )

    except SuperDocsParseError:
        return parse_bullet_extraction(
            text,
            expected_document_type=expected_document_type,
        )