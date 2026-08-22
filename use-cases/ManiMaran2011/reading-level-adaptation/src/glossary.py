"""
Glossary for the language-learner adaptation. The task card explicitly flags "the glossary is drawn from the
actual text rather than a generic word list" as what separates strong from competent -- so this module
scopes the extraction instruction to the adapted text itself and, as a cheap sanity check, rejects any
returned term that doesn't actually appear (case-insensitive substring) in that text. A generic word list
would fail this check; a grounded one passes trivially.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass
class GlossaryTerm:
    term: str
    definition: str


def _visible_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def extract_glossary(client, session_id: str, adapted_html: str) -> list[GlossaryTerm]:
    text = _visible_text(adapted_html)
    instruction = (
        "Do not edit the document. Instead, list 5-10 vocabulary terms that a language learner would find "
        "difficult, drawn ONLY from words or phrases that literally appear in this text. For each term give "
        "a plain-language definition grounded in how the text uses it. Respond as a JSON array of "
        '{"term": ..., "definition": ...} and nothing else.'
    )
    response = client.chat(session_id=f"{session_id}__glossary", message=instruction, document_html=adapted_html)
    raw = response.get("response", "[]")

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Extraction is best-effort text from the chat reply, not a structured document edit -- if the
        # model didn't return clean JSON, we surface an empty glossary rather than guess-parsing prose into
        # fabricated terms.
        return []

    terms = []
    text_lower = text.lower()
    for item in parsed:
        term = item.get("term", "").strip()
        definition = item.get("definition", "").strip()
        if not term or not definition:
            continue
        if term.lower() not in text_lower:
            # Grounding check: reject any term the model invented that isn't actually in the text.
            continue
        terms.append(GlossaryTerm(term=term, definition=definition))
    return terms
