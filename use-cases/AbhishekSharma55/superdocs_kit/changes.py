"""Normalising proposed / applied changes.

THE GOTCHA THIS FILE EXISTS FOR
-------------------------------
SuperDocs sometimes hands back a change list as a JSON-encoded *string*
rather than an array, and sometimes double-encodes it. Integrators who
call ``change["new_html"]`` on that string get ``undefined``/``TypeError``
and conclude the diff is empty. It is not empty; it is one ``json.loads``
away.

The fix here is deliberately written against the whole CLASS of the
problem rather than the one field where we first met it:
``deep_parse`` unwraps *any* JSON-in-a-string, at any depth, up to a bound,
and ``changes_from`` applies it to every container the API can return a
change list in (``pending_changes``, ``chunk_diffs``, ``changes``,
``metadata.pending_changes``, ``result.document_changes.*``).

That means a future endpoint that string-encodes a *different* field
does not become a new bug for us.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

MAX_UNWRAPS = 4  # bounded: a string of "[" forever must not spin


def deep_parse(value: Any, _depth: int = 0) -> Any:
    """Recursively decode JSON that arrived as a string.

    ``'"[{\\"a\\":1}]"'`` -> ``[{"a": 1}]``. Anything that is not JSON is
    returned untouched, so this is safe to run over ordinary prose.
    """
    if _depth >= MAX_UNWRAPS:
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("[", "{", '"') and stripped[-1:] in ("]", "}", '"'):
            try:
                return deep_parse(json.loads(stripped), _depth + 1)
            except (json.JSONDecodeError, ValueError):
                return value
        return value
    if isinstance(value, list):
        return [deep_parse(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: deep_parse(v, _depth + 1) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class Change:
    """One proposed or applied section-level edit."""

    change_id: str
    operation: str  # edit | create | delete
    chunk_id: str | None
    document_id: str | None
    old_html: str | None
    new_html: str | None
    explanation: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Change":
        d = deep_parse(d)
        if not isinstance(d, dict):  # a bare string slipped through
            return cls("", "unknown", None, None, None, str(d), None)
        return cls(
            change_id=str(d.get("change_id") or d.get("id") or ""),
            operation=str(d.get("operation") or d.get("op") or "edit"),
            chunk_id=d.get("chunk_id"),
            document_id=d.get("document_id"),
            old_html=d.get("old_html"),
            new_html=d.get("new_html"),
            explanation=d.get("ai_explanation") or d.get("explanation"),
        )


_CHANGE_CONTAINERS = ("pending_changes", "chunk_diffs", "changes")


def changes_from(payload: Any) -> list[Change]:
    """Pull every change out of any SuperDocs response shape.

    Accepts a ChatResponse, a DocumentChanges, a JobResponse, a raw list, or
    a JSON string of any of those. Returns [] rather than raising, because
    "no changes" is a legitimate, common answer and must not look like a crash.
    """
    payload = deep_parse(payload)
    found: list[Change] = []
    seen: set[str] = set()

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6 or node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        # A dict that IS a change.
        if "change_id" in node and ("new_html" in node or "operation" in node):
            change = Change.from_dict(node)
            fingerprint = f"{change.change_id}|{change.chunk_id}|{change.operation}"
            if fingerprint not in seen:
                seen.add(fingerprint)
                found.append(change)
            return
        for key in _CHANGE_CONTAINERS:
            if key in node:
                walk(node[key], depth + 1)
        for key in ("document_changes", "result", "metadata", "job", "data"):
            if key in node:
                walk(node[key], depth + 1)

    walk(payload)
    return found


def updated_html_from(payload: Any) -> str | None:
    """Find the full updated document HTML wherever this response put it."""
    payload = deep_parse(payload)
    if isinstance(payload, dict):
        for path in (
            ("document_changes", "updated_html"),
            ("result", "document_changes", "updated_html"),
            ("updated_html",),
            ("html",),
        ):
            node: Any = payload
            for part in path:
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if isinstance(node, str) and node.strip():
                return node
    return None
