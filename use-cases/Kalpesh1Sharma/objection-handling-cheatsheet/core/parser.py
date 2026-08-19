from __future__ import annotations

import re

from core.config import (
    BULLET_PREFIXES,
    IGNORED_HEADINGS,
    OBJECTION_PREFIXES,
    RESPONSE_PREFIXES,
)
from core.models import (
    EntryStatus,
    ObjectionEntry,
    ParseResult,
    SourceUnit,
)


def _clean_text(
    value: str,
) -> str:
    value = value.strip()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def _remove_wrapping_quotes(
    value: str,
) -> str:
    value = value.strip()

    quote_pairs = (
        ('"', '"'),
        ("“", "”"),
        ("'", "'"),
    )

    for left, right in quote_pairs:
        if (
            len(value) >= 2
            and value.startswith(left)
            and value.endswith(right)
        ):
            return value[
                len(left):
                -len(right)
            ].strip()

    return value


def _strip_prefix(
    value: str,
    prefixes: tuple[str, ...],
) -> tuple[str, bool]:
    """
    Remove one configured prefix, case-insensitively.
    """

    stripped = value.strip()
    lowered = stripped.casefold()

    for prefix in sorted(
        prefixes,
        key=len,
        reverse=True,
    ):
        prefix_lower = prefix.casefold()

        if lowered.startswith(
            prefix_lower
        ):
            remainder = stripped[
                len(prefix):
            ].strip()

            return (
                remainder,
                True,
            )

    return (
        stripped,
        False,
    )


def _extract_objection(
    text: str,
) -> tuple[str, bool]:
    value, explicit = _strip_prefix(
        text,
        OBJECTION_PREFIXES,
    )

    if explicit:
        return (
            _remove_wrapping_quotes(
                value
            ),
            True,
        )

    stripped = text.strip()

    for bullet in BULLET_PREFIXES:
        if stripped.startswith(
            bullet
        ):
            candidate = stripped[
                len(bullet):
            ].strip()

            if candidate:
                return (
                    _remove_wrapping_quotes(
                        candidate
                    ),
                    True,
                )

    # Quoted standalone statements are treated as objections.
    unquoted = _remove_wrapping_quotes(
        stripped
    )

    if unquoted != stripped:
        return (
            unquoted,
            True,
        )

    # A standalone question is also a strong objection signal.
    if stripped.endswith("?"):
        return (
            stripped,
            True,
        )

    return (
        stripped,
        False,
    )


def _extract_response(
    text: str,
) -> tuple[str, bool]:
    value, explicit = _strip_prefix(
        text,
        RESPONSE_PREFIXES,
    )

    return (
        _remove_wrapping_quotes(
            value
        ),
        explicit,
    )


def _make_source_units(
    lines: list[str],
) -> list[SourceUnit]:
    units: list[SourceUnit] = []

    for position, raw_line in enumerate(
        lines,
        start=1,
    ):
        text = _clean_text(
            raw_line
        )

        if not text:
            continue

        units.append(
            SourceUnit(
                source_id=(
                    f"SRC-{len(units) + 1:03d}"
                ),
                position=position,
                text=text,
            )
        )

    return units


def parse_objection_notes(
    lines: list[str],
) -> ParseResult:
    """
    Parse ordered objection/response notes without inventing content.

    Rules:
    - explicit objection syntax starts a new objection;
    - bullets/quoted lines/questions may also start objections;
    - explicit response markers attach only to the active objection;
    - an unmarked line immediately following an unanswered
      objection may serve as its response;
    - unanswered objections remain in the output as
      MISSING_RESPONSE;
    - source text that cannot be assigned safely is preserved in
      unassigned_source_ids rather than silently discarded.
    """

    source_units = (
        _make_source_units(
            lines
        )
    )

    entries: list[ObjectionEntry] = []
    detected_objections: list[str] = []
    unassigned: list[str] = []
    warnings: list[str] = []

    current: dict | None = None

    def finalize_current() -> None:
        nonlocal current

        if current is None:
            return

        response = current.get(
            "response"
        )

        status = (
            EntryStatus.COMPLETE
            if response
            else EntryStatus.MISSING_RESPONSE
        )

        entries.append(
            ObjectionEntry(
                entry_id=(
                    f"OBJ-{len(entries) + 1:03d}"
                ),
                objection=current[
                    "objection"
                ],
                response=response,
                status=status,
                objection_source_ids=list(
                    current[
                        "objection_source_ids"
                    ]
                ),
                response_source_ids=list(
                    current[
                        "response_source_ids"
                    ]
                ),
            )
        )

        current = None

    for unit in source_units:
        text = unit.text

        if (
            text.casefold()
            in IGNORED_HEADINGS
        ):
            # Known structural content: deliberately ignored,
            # not silently lost.
            continue

        response_text, is_response = (
            _extract_response(
                text
            )
        )

        objection_text, is_objection = (
            _extract_objection(
                text
            )
        )

        # --------------------------------------------------
        # Explicit response
        # --------------------------------------------------

        if is_response:
            if current is None:
                unassigned.append(
                    unit.source_id
                )

                warnings.append(
                    (
                        f"{unit.source_id} looks like a response "
                        "but no active objection exists."
                    )
                )

                continue

            if not response_text:
                warnings.append(
                    (
                        f"{unit.source_id} contains a response "
                        "marker but no response text."
                    )
                )

                continue

            if current.get(
                "response"
            ):
                current[
                    "response"
                ] += (
                    " "
                    + response_text
                )
            else:
                current[
                    "response"
                ] = response_text

            current[
                "response_source_ids"
            ].append(
                unit.source_id
            )

            continue

        # --------------------------------------------------
        # New objection
        # --------------------------------------------------

        if is_objection:

            detected_objections.append(
                unit.source_id
            )
            
            finalize_current()

            current = {
                "objection":
                    objection_text,

                "response":
                    None,

                "objection_source_ids": [
                    unit.source_id
                ],

                "response_source_ids": [],
            }

            continue

        # --------------------------------------------------
        # Plain unmarked text
        # --------------------------------------------------

        if current is not None:
            if current.get(
                "response"
            ):
                # Safe response continuation.
                current[
                    "response"
                ] += (
                    " "
                    + text
                )

                current[
                    "response_source_ids"
                ].append(
                    unit.source_id
                )

            else:
                # This is how inputs such as:
                #
                # * SECURITY???
                # We encrypt data...
                #
                # remain supported without requiring a response
                # marker on every line.
                current[
                    "response"
                ] = text

                current[
                    "response_source_ids"
                ].append(
                    unit.source_id
                )

            continue

        # We do not guess what an orphan plain line means.
        unassigned.append(
            unit.source_id
        )

        warnings.append(
            (
                f"{unit.source_id} could not be safely assigned "
                "to an objection or response."
            )
        )

    finalize_current()

    return ParseResult(
    entries=entries,
    source_units=source_units,
    detected_objection_source_ids=(
        detected_objections
    ),
    unassigned_source_ids=unassigned,
    warnings=warnings,
)