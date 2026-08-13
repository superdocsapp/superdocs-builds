from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .document import Document, DocumentElement


@dataclass(frozen=True)
class DocumentFingerprint:
    """
    Deterministic representation of document structure.

    The raw SHA-256 digest provides a fast equality check while the
    structured payload allows the validator to explain differences.
    """

    digest: str
    element_count: int
    element_counts: dict[str, int]
    structure: tuple[dict[str, Any], ...]


def _normalize_text(text: str) -> str:
    """
    Normalize insignificant whitespace without changing actual words.
    """
    return re.sub(r"\s+", " ", text).strip()


def _normalized_element(element: DocumentElement) -> dict[str, Any]:
    """
    Convert an element into deterministic fingerprint data.

    Text is normalized only for whitespace. Attributes and formatting
    remain explicit so structural changes cannot silently disappear.
    """
    return {
        "type": element.element_type,
        "index": element.index,
        "text": _normalize_text(element.text),
        "attributes": {
            key: _normalize_text(value)
            for key, value in sorted(
                element.attributes.items()
            )
        },
        "formatting": element.formatting,
    }


def fingerprint(document: Document) -> DocumentFingerprint:
    """
    Generate a deterministic fingerprint for a document.
    """
    structure = tuple(
        _normalized_element(element)
        for element in document.elements
    )

    payload = {
        "source_format": document.source_format,
        "metadata": document.metadata,
        "elements": structure,
    }

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

    return DocumentFingerprint(
        digest=digest,
        element_count=len(structure),
        element_counts=document.element_counts(),
        structure=structure,
    )


def same_document(
    before: DocumentFingerprint,
    after: DocumentFingerprint,
) -> bool:
    """
    Fast structural equality check.
    """
    return before.digest == after.digest


def changed_elements(
    before: DocumentFingerprint,
    after: DocumentFingerprint,
) -> list[dict[str, Any]]:
    """
    Produce element-level differences.

    This is intentionally position-aware. If an element changes,
    DocShield reports the old and new normalized representation.
    """
    differences: list[dict[str, Any]] = []

    maximum = max(
        len(before.structure),
        len(after.structure),
    )

    for position in range(maximum):
        old = (
            before.structure[position]
            if position < len(before.structure)
            else None
        )

        new = (
            after.structure[position]
            if position < len(after.structure)
            else None
        )

        if old != new:
            differences.append(
                {
                    "position": position,
                    "before": old,
                    "after": new,
                }
            )

    return differences
