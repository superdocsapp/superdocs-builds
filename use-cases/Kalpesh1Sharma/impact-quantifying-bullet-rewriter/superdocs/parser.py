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
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SuperDocsParseError(
                "pending_changes was a string "
                "but was not valid JSON."
            ) from exc

    if value is None:
        return []

    if not isinstance(value, list):
        raise SuperDocsParseError(
            "pending_changes must be a list "
            "or a JSON-encoded list."
        )

    changes: list[dict[str, Any]] = []

    for item in value:
        if not isinstance(item, dict):
            raise SuperDocsParseError(
                "Every proposed change must be an object."
            )

        changes.append(item)

    return changes


def pending_changes_from_job(
    job: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Extract proposed changes from a SuperDocs job.

    Current Review jobs expose pending_changes inside
    job["metadata"], but fallback locations are supported
    for graceful compatibility.
    """

    metadata = job.get("metadata")

    if isinstance(metadata, dict):
        value = metadata.get(
            "pending_changes"
        )

        if value is not None:
            return parse_pending_changes(
                value
            )

    for key in (
        "pending_changes",
        "result",
        "data",
        "output",
    ):
        value = job.get(key)

        if key in {
            "result",
            "data",
            "output",
        }:
            if isinstance(value, dict):
                value = value.get(
                    "pending_changes"
                )
            else:
                continue

        if value is not None:
            return parse_pending_changes(
                value
            )

    return []