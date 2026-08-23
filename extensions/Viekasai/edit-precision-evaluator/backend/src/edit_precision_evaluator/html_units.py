from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag

_WHITESPACE = re.compile(r"\s+")


def _normalise_attribute(name: str, value: object) -> str:
    if isinstance(value, list):
        value = " ".join(sorted(str(item) for item in value))
    text = str(value).strip()
    if name == "style":
        declarations = [part.strip() for part in text.split(";") if part.strip()]
        return ";".join(sorted(declarations))
    return _WHITESPACE.sub(" ", text)


def _canonical_node(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        text = _WHITESPACE.sub(" ", str(node))
        return text if text.strip() else ""

    attributes = "".join(
        f' {name}="{_normalise_attribute(name, value)}"'
        for name, value in sorted(node.attrs.items())
    )
    children = "".join(_canonical_node(child) for child in node.children)
    return f"<{node.name}{attributes}>{children}</{node.name}>"


def extract_units(document_html: str) -> dict[str, str]:
    """Return canonical HTML for every element carrying a SuperDocs chunk ID."""

    soup = BeautifulSoup(document_html, "html.parser")
    units: dict[str, str] = {}
    for element in soup.select("[data-chunk-id]"):
        chunk_id = str(element.get("data-chunk-id", "")).strip()
        if not chunk_id:
            continue
        if chunk_id in units:
            raise ValueError(f"Duplicate data-chunk-id found: {chunk_id}")
        units[chunk_id] = _canonical_node(element)
    return units


def changed_unit_ids(before_html: str, after_html: str) -> tuple[set[str], set[str]]:
    before = extract_units(before_html)
    after = extract_units(after_html)
    all_ids = set(before) | set(after)
    changed = {chunk_id for chunk_id in all_ids if before.get(chunk_id) != after.get(chunk_id)}
    added = set(after) - set(before)
    return changed, added


def select_unit_html(document_html: str, chunk_ids: Iterable[str]) -> dict[str, str | None]:
    units = extract_units(document_html)
    return {chunk_id: units.get(chunk_id) for chunk_id in chunk_ids}
