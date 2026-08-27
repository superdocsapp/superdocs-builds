

from __future__ import annotations

import copy
from typing import Any

from .models import I18N_KEY, Property, SharedBlock, _deep_merge, is_i18n


def deep_merge_copy(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Pure merge: returns a new dict; inputs are never mutated."""
    merged = copy.deepcopy(base)
    _deep_merge(merged, override)
    return merged


def resolve(kind: str,
            prop: Property,
            blocks: dict[str, SharedBlock]) -> dict[str, Any]:
    """Effective content for one section of one property."""
    override = prop.overrides.get(kind, {})
    block_id = prop.links.get(kind)
    if block_id is None:
        if not override:
            raise KeyError(
                f"Property '{prop.id}' has no '{kind}' block linked and no overrides."
            )
        return copy.deepcopy(override)
    block = blocks.get(block_id)
    if block is None:
        from .errors import MissingLink
        raise MissingLink(prop.id, kind, block_id)
    if block.kind != kind:
        raise ValueError(
            f"Property '{prop.id}' links '{kind}' to block '{block_id}' "
            f"of mismatched kind '{block.kind}'."
        )
    return deep_merge_copy(block.content, override)


def resolve_all(prop: Property,
                blocks: dict[str, SharedBlock],
                kinds: list[str] | None = None) -> dict[str, dict[str, Any]]:
    kinds = kinds or sorted(set(prop.links) | set(prop.overrides))
    return {kind: resolve(kind, prop, blocks) for kind in kinds}


def localized(node: Any, lang: str, base_lang: str = "en") -> str:
    from .models import resolve_text
    return resolve_text(node, lang, base_lang)


def strip_i18n(value: Any) -> Any:
    """Flatten localized nodes to plain strings (for listing text exports)."""
    if is_i18n(value):
        from .models import resolve_text
        return resolve_text(value, "en", "en")
    if isinstance(value, dict):
        return {k: strip_i18n(v) for k, v in value.items() if k != I18N_KEY}
    if isinstance(value, list):
        return [strip_i18n(v) for v in value]
    return value
