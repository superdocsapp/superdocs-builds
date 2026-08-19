from __future__ import annotations

import json
from typing import Any


class SuperDocsParseError(ValueError):
    pass


def parse_pending_changes(
    value: Any,
) -> list[dict[str, Any]]:
    """
    SuperDocs pending changes may arrive either:
    - already as a list
    - as a JSON-encoded string

    Never silently treat malformed content as an
    empty successful diff.
    """

    if isinstance(value, str):
        try:
            value = json.loads(
                value
            )
        except json.JSONDecodeError as exc:
            raise SuperDocsParseError(
                "pending_changes was a string "
                "but was not valid JSON."
            ) from exc

    if value is None:
        return []

    if not isinstance(
        value,
        list,
    ):
        raise SuperDocsParseError(
            "pending_changes must be a list "
            "or a JSON-encoded list."
        )

    changes: list[dict[str, Any]] = []

    for item in value:
        if not isinstance(
            item,
            dict,
        ):
            raise SuperDocsParseError(
                "Every proposed change must "
                "be an object."
            )

        changes.append(
            item
        )

    return changes