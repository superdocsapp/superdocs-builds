from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .models import CorpusCase, LabelScope

_WHITESPACE = re.compile(r"\s+")


def _elements(document_html: str) -> list[tuple[str, tuple[str, str]]]:
    soup = BeautifulSoup(document_html, "html.parser")
    result: list[tuple[str, tuple[str, str]]] = []
    for element in soup.select("[data-chunk-id]"):
        if not isinstance(element, Tag):
            continue
        chunk_id = str(element.get("data-chunk-id", "")).strip()
        text = _WHITESPACE.sub(" ", element.get_text(" ", strip=True))
        result.append((chunk_id, (element.name, text)))
    return result


def align_chunk_ids(
    original_html: str, uploaded_html: str, required_ids: set[str]
) -> dict[str, str]:
    """Map corpus IDs to IDs returned by SuperDocs upload without using ground-truth scope.

    Existing IDs win. If upload regenerated IDs, structural tag + exact pre-edit text is used.
    This alignment happens before any instruction is sent and never enters an edit prompt.
    """

    original = _elements(original_html)
    uploaded = _elements(uploaded_html)
    original_by_id = dict(original)
    uploaded_ids = {chunk_id for chunk_id, _ in uploaded}
    used_uploaded: set[str] = set()
    mapping: dict[str, str] = {}

    for original_id in required_ids:
        if original_id in uploaded_ids:
            mapping[original_id] = original_id
            used_uploaded.add(original_id)
            continue
        fingerprint = original_by_id.get(original_id)
        if fingerprint is None:
            raise ValueError(f"Original document is missing labelled chunk {original_id}")
        candidates = [
            uploaded_id
            for uploaded_id, uploaded_fingerprint in uploaded
            if uploaded_fingerprint == fingerprint and uploaded_id not in used_uploaded
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Could not uniquely align labelled chunk {original_id}; candidates={candidates}"
            )
        mapping[original_id] = candidates[0]
        used_uploaded.add(candidates[0])
    return mapping


def remap_case(case: CorpusCase, mapping: dict[str, str]) -> CorpusCase:
    scopes: list[LabelScope] = []
    for scope in case.acceptable_scopes:
        scopes.append(
            scope.model_copy(
                update={
                    "expected_change_ids": {mapping[item] for item in scope.expected_change_ids},
                    "protected_ids": {mapping[item] for item in scope.protected_ids},
                    "required_after_fragments": {
                        mapping[key]: value for key, value in scope.required_after_fragments.items()
                    },
                    "forbidden_after_fragments": {
                        mapping[key]: value
                        for key, value in scope.forbidden_after_fragments.items()
                    },
                }
            )
        )
    return case.model_copy(update={"acceptable_scopes": scopes})
