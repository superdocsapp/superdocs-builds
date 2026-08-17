"""The scripted correction protocol.

`generate_corrections(text, rubric)` is a pure function: the same document text
produces byte-identical corrections, every time, in both arms. No model call, no
human, no improvisation. This is the constraint the brief names as the single
most important one in the task — a human improvising corrections gets better at
correcting as they go, and that improvement lands silently in whichever arm runs
second.

Three things enforce it here:

1. No arm parameter exists. The signature cannot carry the arm, the run id, or
   the document ordinal, so the protocol has no way to differ between arms.
2. Corrections derive only from the committed checker's score and the committed
   template table. Both are data, both are versioned.
3. H3 is the one rule whose score comes from a model. Its result is cached by
   content hash, so a document that has been scored once yields the same H3
   correction forever — including when the other arm produces the same text.
   Without the cache, a model that wavered at temperature 0 could hand the two
   arms different corrections for identical output.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from checker.h3 import H3Provider, strip_fence
from checker.score import DocumentScore, score_document

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_PATH = ROOT / "corrections" / "templates.json"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def load_templates() -> dict:
    with open(TEMPLATES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _rule_sort_key(rule_id: str) -> tuple[int, str]:
    """H2 before H10. Lexicographic ordering would put H10 second."""
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", rule_id)
    return (int(m.group(2)), m.group(1)) if m else (10**6, rule_id)


def sanitize_span(span: str, max_chars: int) -> str:
    """Flatten a quoted span to a single safe line.

    Spans come from document content, which is untrusted: a document could
    contain text addressed to the agent. Newlines and control characters are
    removed so a span cannot forge a new instruction line in the correction
    payload, and the preamble states that quoted text is content, not
    instruction.
    """
    flat = _WHITESPACE.sub(" ", _CONTROL_CHARS.sub("", span)).strip()
    if len(flat) > max_chars:
        flat = flat[:max_chars].rstrip() + "..."
    return f'"{flat}"'


@dataclass(frozen=True)
class Correction:
    rule_id: str
    message: str
    span: str


@dataclass
class CorrectionSet:
    corrections: list[Correction] = field(default_factory=list)
    templates_version: str = ""
    rubric_version: str = ""
    rules_violated: int = 0
    rules_corrected: int = 0

    @property
    def payload(self) -> str:
        """The exact string sent to `chat`. Empty when nothing was violated."""
        if not self.corrections:
            return ""
        lines = [load_templates()["preamble"], ""]
        lines += [f"{i}. {c.message}"
                  for i, c in enumerate(self.corrections, start=1)]
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "templates_version": self.templates_version,
            "rubric_version": self.rubric_version,
            "rules_violated": self.rules_violated,
            "rules_corrected": self.rules_corrected,
            "corrections": [{"rule_id": c.rule_id, "span": c.span,
                             "message": c.message} for c in self.corrections],
            "payload_sha256": hashlib.sha256(
                self.payload.encode("utf-8")).hexdigest()[:16],
        }


class H3Cache:
    """Content-hash keyed cache for the one model-scored rule.

    Guarantees that identical document text yields an identical H3 result, so
    two arms producing the same output receive the same corrections even if the
    model would not repeat itself.
    """

    def __init__(self, path: Path | None = None):
        self.path = path
        self._data: dict[str, dict] = {}
        if path and path.exists():
            self._data = json.loads(path.read_text("utf-8"))

    def key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def get(self, text: str) -> dict | None:
        return self._data.get(self.key(text))

    def put(self, text: str, result: dict) -> None:
        self._data[self.key(text)] = result
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True)
                                 + "\n", encoding="utf-8")


class _CachedH3Provider(H3Provider):
    """Wraps a provider so a given document text is scored at most once ever."""

    def __init__(self, inner: H3Provider, cache: H3Cache):
        self.inner, self.cache = inner, cache

    def complete(self, document_text: str) -> str:
        hit = self.cache.get(document_text)
        if hit is not None:
            return json.dumps(hit)
        raw = self.inner.complete(document_text)
        try:
            # Must match score_h3's own parsing exactly (fence-stripped), or a
            # fenced response scores correctly downstream while silently never
            # getting cached — found live: Gemini fences its JSON by default,
            # so the cache stayed empty through a whole arm of real scoring.
            parsed = json.loads(strip_fence(raw))
        except json.JSONDecodeError:
            return raw  # let the checker's retry/degradation path handle it
        self.cache.put(document_text, parsed)
        return raw


def corrections_from_score(score: DocumentScore, templates: dict | None = None
                           ) -> CorrectionSet:
    """Build corrections from an already-computed score. Pure and total."""
    templates = templates or load_templates()
    table = templates["templates"]
    max_rules = templates["max_rules_per_round"]
    max_span = templates["max_span_chars"]

    violated = [rid for rid, r in score.rules.items()
                if r.count_raw > 0 and r.spans and rid in table]
    violated.sort(key=_rule_sort_key)

    out: list[Correction] = []
    for rule_id in violated[:max_rules]:
        # One message per rule, however many instances it has: a document with
        # forty contractions must not generate forty messages.
        span = score.rules[rule_id].spans[0]
        safe = sanitize_span(span, max_span)
        out.append(Correction(rule_id=rule_id,
                              message=table[rule_id].format(span=safe),
                              span=safe))

    return CorrectionSet(corrections=out,
                         templates_version=templates["version"],
                         rubric_version=score.rubric_version,
                         rules_violated=len(violated),
                         rules_corrected=len(out))


def generate_corrections(text: str, rubric: dict,
                         h3_provider: H3Provider | None = None,
                         h3_cache: H3Cache | None = None) -> CorrectionSet:
    """Scripted corrections for one document. No arm, run, or ordinal accepted."""
    provider = h3_provider
    if provider is not None and h3_cache is not None:
        provider = _CachedH3Provider(provider, h3_cache)
    score = score_document(text, rubric, provider)
    return corrections_from_score(score)
