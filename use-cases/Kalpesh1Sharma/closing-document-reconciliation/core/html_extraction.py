from __future__ import annotations

import html
import re


"""Deterministic field extraction from SuperDocs processed HTML.

The module intentionally performs no AI inference. It only maps explicit
labels and adjacent values from the HTML returned by SuperDocs into the
canonical extraction payload consumed by ``core.extraction``.
"""

DOCUMENT_MARKERS = {
    "loan_estimate": ["loan estimate"],
    "closing_disclosure": ["closing disclosure"],
    "promissory_note": ["promissory note"],
    "settlement_statement": ["settlement statement"],
    "underwriting_approval": ["underwriting approval"],
}


FIELD_ALIASES = {
    "borrower_names": [
        "approved borrowers",
        "borrower(s)",
        "borrowers",
        "applicants",
    ],
    "property_address": [
        "approved property",
        "settlement property",
        "secured property",
        "property location",
        "property address",
    ],
    "loan_amount": [
        "principal amount of new loan",
        "approved principal",
        "amount of loan",
        "principal sum",
        "loan amount",
    ],
    "interest_rate": [
        "approved note rate",
        "interest rate",
        "interest",
    ],
    "term": [
        "amortization term",
        "loan term",
        "maturity",
    ],
    "escrow": [
        "escrow property costs",
        "escrow requirement",
        "escrow collected",
        "escrow account",
    ],
    "origination": [
        "loan costs — origination",
        "loan costs - origination",
        "origination charges",
    ],
    "title_services": [
        "title & settlement services",
        "settlement / title charges",
        "title services",
    ],
    "cash_to_close": [
        "estimated cash to close",
        "amount due from borrower",
        "cash to close",
    ],
}


def html_to_lines(
    document_html: str,
) -> list[str]:
    """
    Convert SuperDocs HTML into stable logical lines.

    Each table cell becomes its own line so labels in later cells
    are not hidden behind earlier cells in the same row.
    """

    if not document_html:
        return []

    value = document_html

    value = re.sub(
        r"(?i)<br\s*/?>",
        "\n",
        value,
    )

    value = re.sub(
        r"(?i)</(?:td|th)>",
        "\n",
        value,
    )

    value = re.sub(
        r"(?i)</(?:p|div|tr|li|h[1-6]|section|article)>",
        "\n",
        value,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = html.unescape(value)
    value = value.replace("\xa0", " ")

    lines: list[str] = []

    for raw_line in value.splitlines():
        line = re.sub(
            r"\s+",
            " ",
            raw_line,
        ).strip()

        line = line.strip(" |")

        if line:
            lines.append(line)

    return lines


def _normalized_label(
    value: str,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        value.casefold(),
    ).strip()


def infer_document_type(
    *,
    filename: str,
    lines: list[str],
) -> str:
    """
    Detect the document type without letting references to other
    mortgage documents override the document's own title.

    Priority:
    1. Earliest explicit type marker in the document header.
    2. A unique type marker in the filename.
    3. A unique type marker anywhere in the document.
    4. Otherwise return unknown rather than guess.

    This prevents an Underwriting Approval from being classified as
    a Loan Estimate merely because one of its rules mentions
    "Loan Estimate".
    """

    # --------------------------------------------------------
    # 1. Prefer the earliest marker in the document header.
    # --------------------------------------------------------
    header_candidates: list[
        tuple[int, int, int, str]
    ] = []

    for line_index, line in enumerate(
        lines[:15]
    ):
        normalized_line = (
            _normalized_label(line)
        )

        for document_type, markers in (
            DOCUMENT_MARKERS.items()
        ):
            for marker in markers:
                position = (
                    normalized_line.find(
                        marker
                    )
                )

                if position >= 0:
                    header_candidates.append(
                        (
                            line_index,
                            position,
                            -len(marker),
                            document_type,
                        )
                    )

    if header_candidates:
        header_candidates.sort()
        return header_candidates[0][3]

    # --------------------------------------------------------
    # 2. Use filename only when it identifies one type.
    # --------------------------------------------------------
    filename_text = (
        Path(filename)
        .stem
        .replace("_", " ")
        .replace("-", " ")
        .casefold()
    )

    filename_matches: list[str] = []

    for document_type, markers in (
        DOCUMENT_MARKERS.items()
    ):
        if any(
            marker in filename_text
            for marker in markers
        ):
            filename_matches.append(
                document_type
            )

    if len(filename_matches) == 1:
        return filename_matches[0]

    # --------------------------------------------------------
    # 3. Whole-document fallback only if unambiguous.
    # --------------------------------------------------------
    searchable = " ".join(
        lines
    ).casefold()

    content_matches: list[str] = []

    for document_type, markers in (
        DOCUMENT_MARKERS.items()
    ):
        if any(
            marker in searchable
            for marker in markers
        ):
            content_matches.append(
                document_type
            )

    if len(content_matches) == 1:
        return content_matches[0]

    # Ambiguous is safer than choosing the first matching phrase.
    return "unknown"


def _line_looks_like_field_label(
    line: str,
) -> bool:
    normalized = _normalized_label(line)

    for aliases in FIELD_ALIASES.values():
        for alias in aliases:
            alias_normalized = _normalized_label(alias)

            if (
                normalized == alias_normalized
                or normalized.startswith(
                    alias_normalized + ":"
                )
                or normalized.startswith(
                    alias_normalized + " |"
                )
            ):
                return True

    return False


def _extract_value(
    *,
    lines: list[str],
    aliases: list[str],
) -> dict[str, str | None]:
    """
    Find an explicit field label and its adjacent value.

    Safeguards:
    - "Loan Term" does not match the heading "Loan Terms".
    - "Applicants" does not turn "Applicants and Property" into
      the borrower value "and Property".
    - Rule text is never used as a field value.
    """

    aliases = sorted(
        aliases,
        key=len,
        reverse=True,
    )

    for index, line in enumerate(lines):
        if re.search(
            r"\bR-\d{3}\b",
            line,
            flags=re.IGNORECASE,
        ):
            continue

        lowered = _normalized_label(line)

        for alias in aliases:
            alias_lower = _normalized_label(alias)
            position = lowered.find(alias_lower)

            if position < 0:
                continue

            prefix = lowered[:position].strip(
                " :|-–—"
            )

            if prefix and prefix not in {
                "field",
                "field value",
                "value",
            }:
                continue

            alias_end = position + len(alias_lower)

            if alias_end < len(lowered):
                next_character = lowered[alias_end]

                # Prevent substring matches such as
                # "loan term" inside "loan terms".
                if next_character.isalnum():
                    continue

            original_end = position + len(alias)

            remainder = line[
                original_end:
            ].strip()

            remainder = remainder.lstrip(
                " :|-–—"
            ).strip()

            if remainder:
                # Section headings such as "Applicants and Property"
                # are not field/value pairs.
                if remainder.casefold().startswith(
                    ("and ", "& ")
                ):
                    continue

                return {
                    "raw_value": remainder,
                    "supporting_quote": line,
                }

            if index + 1 < len(lines):
                next_line = (
                    lines[index + 1]
                    .strip()
                    .strip(" |")
                )

                if (
                    next_line
                    and not re.search(
                        r"\bR-\d{3}\b",
                        next_line,
                        flags=re.IGNORECASE,
                    )
                    and not _line_looks_like_field_label(
                        next_line
                    )
                ):
                    return {
                        "raw_value": next_line,
                        "supporting_quote": (
                            f"{line} {next_line}"
                        ),
                    }

    return {
        "raw_value": None,
        "supporting_quote": None,
    }


def _extract_composite_label_value(
    *,
    lines: list[str],
    label_parts: list[str],
) -> dict[str, str | None]:
    """
    Handle labels that SuperDocs may split across adjacent block/cell
    boundaries, for example:

        Property
        Address
        812 Cedar Grove Drive, Austin, TX 78704

    or:

        Escrow
        Property Costs
        Yes

    The match is exact for each label part, so generic words such as
    "Property" cannot accidentally capture "Property Costs".
    """

    normalized_parts = [
        _normalized_label(
            part
        )
        for part in label_parts
    ]

    part_count = len(
        normalized_parts
    )

    if part_count == 0:
        return {
            "raw_value": None,
            "supporting_quote": None,
        }

    for start in range(
        0,
        len(lines) - part_count,
    ):
        candidate = [
            _normalized_label(
                lines[start + offset]
            )
            for offset in range(
                part_count
            )
        ]

        if candidate != normalized_parts:
            continue

        value_index = (
            start
            + part_count
        )

        if value_index >= len(lines):
            continue

        value = (
            lines[value_index]
            .strip()
            .strip(" |")
        )

        if not value:
            continue

        if re.search(
            r"\bR-\d{3}\b",
            value,
            flags=re.IGNORECASE,
        ):
            continue

        if _line_looks_like_field_label(
            value
        ):
            continue

        quote = " ".join(
            lines[
                start:
                value_index + 1
            ]
        )

        return {
            "raw_value":
                value,
            "supporting_quote":
                quote,
        }

    return {
        "raw_value": None,
        "supporting_quote": None,
    }


def extract_rules(
    lines: list[str],
) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    seen: set[str] = set()

    rule_pattern = re.compile(
        r"\b(R-\d{3})\b\s*[:\-–—|]?\s*(.*)",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):
        match = rule_pattern.search(
            line
        )

        if not match:
            continue

        rule_id = (
            match.group(1)
            .upper()
        )

        if rule_id in seen:
            continue

        rule_text = (
            match.group(2)
            .strip()
            .lstrip(" :|-–—")
            .strip()
        )

        supporting_quote = line

        if (
            not rule_text
            and index + 1 < len(lines)
        ):
            rule_text = (
                lines[index + 1]
                .strip()
            )

            supporting_quote = (
                f"{line} {rule_text}"
            )

        if not rule_text:
            continue

        seen.add(
            rule_id
        )

        rules.append({
            "rule_id":
                rule_id,
            "rule_text":
                rule_text,
            "supporting_quote":
                supporting_quote,
        })

    return rules


def extract_from_superdocs_html(
    *,
    filename: str,
    document_html: str,
) -> dict:
    lines = html_to_lines(
        document_html
    )

    document_type = infer_document_type(
        filename=filename,
        lines=lines,
    )

    borrower_names = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "borrower_names"
        ],
    )

    property_address = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "property_address"
        ],
    )

    loan_amount = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "loan_amount"
        ],
    )

    interest_rate = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "interest_rate"
        ],
    )

    term = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "term"
        ],
    )

    escrow = _extract_value(
        lines=lines,
        aliases=FIELD_ALIASES[
            "escrow"
        ],
    )

    # SuperDocs can preserve stacked table headings as separate logical
    # lines. Closing Disclosures commonly render these two labels as:
    #
    #   Property / Address / <value>
    #   Escrow / Property Costs / <value>
    #
    # Only use these exact composite-label fallbacks when the normal
    # explicit alias extraction did not find a value.
    if (
        document_type
        == "closing_disclosure"
    ):
        # The actual SuperDocs HTML for the Closing Disclosure uses
        # exact table labels "Property" and "Escrowed Property Costs".
        # Keep these aliases document-specific so generic "Property"
        # cannot affect other document types.

        if (
            property_address.get(
                "raw_value"
            )
            is None
        ):
            property_address = (
                _extract_value(
                    lines=lines,
                    aliases=[
                        "property",
                    ],
                )
            )

        if (
            escrow.get(
                "raw_value"
            )
            is None
        ):
            escrow = (
                _extract_value(
                    lines=lines,
                    aliases=[
                        "escrowed property costs",
                    ],
                )
            )

        # Retain stacked-label fallbacks for alternate renderings.
        if (
            property_address.get(
                "raw_value"
            )
            is None
        ):
            property_address = (
                _extract_composite_label_value(
                    lines=lines,
                    label_parts=[
                        "Property",
                        "Address",
                    ],
                )
            )

        if (
            escrow.get(
                "raw_value"
            )
            is None
        ):
            escrow = (
                _extract_composite_label_value(
                    lines=lines,
                    label_parts=[
                        "Escrow",
                        "Property Costs",
                    ],
                )
            )

    return {
        "document_type":
            document_type,

        "borrower_names":
            borrower_names,

        "property_address":
            property_address,

        "loan_amount":
            loan_amount,

        "interest_rate":
            interest_rate,

        "term":
            term,

        "escrow":
            escrow,

        "fees": {
            "origination":
                _extract_value(
                    lines=lines,
                    aliases=FIELD_ALIASES[
                        "origination"
                    ],
                ),

            "title_services":
                _extract_value(
                    lines=lines,
                    aliases=FIELD_ALIASES[
                        "title_services"
                    ],
                ),
        },

        "cash_to_close":
            _extract_value(
                lines=lines,
                aliases=FIELD_ALIASES[
                    "cash_to_close"
                ],
            ),

        "rules":
            extract_rules(
                lines
            ),
    }
