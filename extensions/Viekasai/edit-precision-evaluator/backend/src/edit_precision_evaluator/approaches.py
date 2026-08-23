from __future__ import annotations

import json
import re

SEARCH_PROMPT = """Search the supplied document for the section or sections targeted by the edit instruction below.
Do not edit the document. Return only JSON in this exact shape: {{"chunk_ids":["id"]}}.
Use the data-chunk-id values from the document and include only likely edit targets.

Edit instruction: {instruction}
"""


def direct_prompt(instruction: str) -> str:
    return instruction


def search_prompt(instruction: str) -> str:
    return SEARCH_PROMPT.format(instruction=instruction)


def parse_search_chunk_ids(response_text: str) -> list[str]:
    candidates = [response_text.strip()]
    candidates.extend(re.findall(r"\{.*?\}", response_text, flags=re.DOTALL))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("chunk_ids"), list):
            continue
        return list(
            dict.fromkeys(
                item.strip()
                for item in value["chunk_ids"]
                if isinstance(item, str) and item.strip()
            )
        )
    return []


def scoped_edit_prompt(instruction: str, chunk_ids: list[str]) -> str:
    if not chunk_ids:
        scope = "The search step found no reliable chunk ID; identify the narrowest valid scope."
    else:
        scope = "Search identified these likely target chunks: " + ", ".join(chunk_ids) + "."
    return (
        f"{scope}\nApply the original instruction only within its necessary scope. "
        "Preserve every unrelated chunk, its wording, and its formatting.\n\n"
        f"Original instruction: {instruction}"
    )
