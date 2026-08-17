"""H3 (passive voice) — the one rule that needs model judgment.

Providers return the JSON contract defined in checker/prompts/h3_passive_v1.md.
Post-processing here is provider-independent and is where the anti-hallucination
check lives: a returned clause that does not appear verbatim in the source is
discarded, and the verified length is used as the count rather than the model's
own `count` field.

On the mock: the brief's Task 1 lesson is that a mock can be *worse* than the
real thing when it is too well behaved. `MockH3Provider` therefore implements a
real be-verb + past-participle heuristic with the same adjectival-participle
exception list the prompt gives the model — it finds real passives, misses the
same edge cases a small model misses, and returns the same JSON shape. Two
adversarial providers exist alongside it precisely because a well-behaved mock
hides bugs: one hallucinates a clause that is not in the text, one fails hard.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .document import Document, split_sentences

PROMPT_VERSION = "h3_passive_v1"

_BE = r"(?:is|are|was|were|be|been|being|get|gets|got)"

_IRREGULAR_PARTICIPLES = {
    "approved", "reviewed", "sent", "written", "made", "taken", "given",
    "seen", "done", "held", "built", "drawn", "shown", "kept", "paid",
    "brought", "found", "chosen", "signed", "raised", "flagged", "issued",
}

# Adjectival participles the prompt explicitly tells the model NOT to count.
_ADJECTIVAL = {
    "required", "committed", "closed", "involved", "located", "based",
    "known", "limited", "related", "interested", "concerned", "founded",
    "pleased", "prepared", "aware", "finished", "gone", "due",
}


@dataclass
class H3Result:
    count_raw: int
    clauses: list[str]
    status: str = "ok"  # "ok" | "checker_error"


class H3Provider:
    """Interface. Returns the raw JSON string the model would return."""

    def complete(self, document_text: str) -> str:  # pragma: no cover
        raise NotImplementedError


class MockH3Provider(H3Provider):
    """Keyless stand-in that behaves like the real scorer, not better than it."""

    def complete(self, document_text: str) -> str:
        clauses: list[str] = []
        for sentence in _sentences(document_text):
            for m in re.finditer(
                    rf"\b{_BE}\s+(?:\w+ly\s+)?(\w+)\b", sentence, re.IGNORECASE):
                word = m.group(1).lower()
                if word in _ADJECTIVAL:
                    continue
                if not (word.endswith("ed") or word.endswith("en")
                        or word in _IRREGULAR_PARTICIPLES):
                    continue
                clauses.append(sentence.strip())
                break  # one clause per sentence in the mock's simple model
        return json.dumps({"count": len(clauses), "clauses": clauses})


class HallucinatingH3Provider(H3Provider):
    """Adversarial: returns a clause that is not in the document."""

    def complete(self, document_text: str) -> str:
        real = json.loads(MockH3Provider().complete(document_text))
        real["clauses"].append("This clause was never in the document.")
        real["count"] = len(real["clauses"])
        return json.dumps(real)


class FailingH3Provider(H3Provider):
    """Adversarial: never returns parseable JSON."""

    def __init__(self, error: str = "503 upstream unavailable"):
        self.error = error
        self.calls = 0

    def complete(self, document_text: str) -> str:
        self.calls += 1
        return self.error


_PROMPT_PATH = (Path(__file__).resolve().parent.parent / "checker" / "prompts"
                / "h3_passive_v1.md")


def _load_h3_prompt_template() -> str:
    """Extract the committed, immutable prompt body from h3_passive_v1.md."""
    text = _PROMPT_PATH.read_text("utf-8")
    start = text.index("## Prompt body (sent verbatim)")
    body = text[start:].split("\n", 1)[1]
    return body.split("## Post-processing")[0].strip()


class GeminiH3Provider(H3Provider):
    """Real provider. Constructed only when a key is present; never in tests.

    Sends exactly the committed prompt in checker/prompts/h3_passive_v1.md, at
    temperature 0, with only the document text substituted in. The blinding
    contract lives in that file: no arm label, run id, ordinal, or client id is
    ever part of what gets sent.
    """

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash-lite"):
        if not api_key:
            raise ValueError("GEMINI_API_KEY required for the live H3 provider")
        self.api_key = api_key
        self.model = model
        self._template = _load_h3_prompt_template()

    def complete(self, document_text: str) -> str:
        import gemini_client
        prompt = self._template.replace("{{DOCUMENT_TEXT}}", document_text)
        return gemini_client.call_gemini(prompt, self.api_key,
                                         model=self.model, temperature=0)


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip().lstrip("#").lstrip("-*+ ").strip()
        if line:
            out.extend(split_sentences(line))
    return out


def score_h3(doc: Document, provider: H3Provider, cap: int = 5) -> H3Result:
    """Run the provider, verify every clause verbatim, retry once on failure."""
    source = doc.raw
    for attempt in (1, 2):
        raw = provider.complete(doc.body_text)
        try:
            payload = json.loads(strip_fence(raw))
            clauses = [c for c in payload.get("clauses", []) if isinstance(c, str)]
        except (json.JSONDecodeError, AttributeError):
            if attempt == 2:
                return H3Result(count_raw=0, clauses=[], status="checker_error")
            continue
        verified = [c for c in clauses if c.strip() and c.strip() in source]
        return H3Result(count_raw=len(verified), clauses=verified)
    return H3Result(count_raw=0, clauses=[], status="checker_error")


def strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\s*", "", raw)
        raw = re.sub(r"```$", "", raw).strip()
    return raw
