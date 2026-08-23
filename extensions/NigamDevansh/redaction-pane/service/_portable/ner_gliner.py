# ─────────────────────────────────────────────────────────────────────
# COPIED FILE — do not edit here.
# Source: packages/core/src/doctask_core/portable/ner_gliner.py
# Refresh: uv run python scripts/sync_portable.py
# This app is standalone by design and imports nothing outside itself.
# ─────────────────────────────────────────────────────────────────────
"""GLiNER wrapper — span-level NER with caller-supplied labels.

PORTABLE: zero internal imports.
Source of truth. Copies live in each extension's `_portable/`.

Two consumers, one model: T2.1's PII tier 2 and T1's party extraction. The rule
that shapes every method: a load failure is never "no entities found". GLiNER is
optional and its model may be absent — both fine, both must be visible, because
returning an empty list on failure would report "no PII" for a document never
scanned.

See docs/CORE_INTERNALS.md § "Module map — two zones".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelUnavailable(Exception):
    """Declared inline. Carries what a person needs to act on it."""

    def __init__(self, *, model: str, env_var: str, capability: str) -> None:
        self.model = model
        self.env_var = env_var
        self.capability = capability
        super().__init__(
            f"Could not load {model!r} (set by {env_var}). Unavailable capability: {capability}."
        )


@dataclass(frozen=True, slots=True)
class Span:
    """Offsets index into the text that was passed in — never a normalised copy."""

    text: str
    label: str
    start: int
    end: int
    score: float


class NERClient(Protocol):
    def extract(self, text: str, labels: list[str], *, threshold: float) -> list[Span]: ...


class GLiNERClient:
    """Lazy-loads on first use, so importing this module costs nothing."""

    def __init__(
        self,
        *,
        model_name: str = "knowledgator/gliner-pii-base-v1.0",
        env_var: str = "GLINER_MODEL",
        capability: str = "PII tier 2 and party candidate extraction",
        cache_dir: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.env_var = env_var
        self.capability = capability
        self.cache_dir = cache_dir
        """Explicit, not just `HF_HOME`. The image bakes models into
        `/opt/models`; a local run may point at a project cache. Passing the
        directory means neither depends on which env var was exported."""
        self._model: Any = None
        self._load_error: Exception | None = None

    def _unavailable(self) -> ModelUnavailable:
        return ModelUnavailable(
            model=self.model_name, env_var=self.env_var, capability=self.capability
        )

    def load(self) -> Any:
        """Load once. A failure is remembered, so a long pile does not retry a
        300MB download per document — the first failure is the answer."""
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise self._unavailable() from self._load_error
        try:
            from gliner import GLiNER

            self._model = GLiNER.from_pretrained(self.model_name, cache_dir=self.cache_dir)
        except Exception as exc:  # noqa: BLE001 — missing package, no net, bad id
            self._load_error = exc
            raise self._unavailable() from exc
        return self._model

    @property
    def is_available(self) -> bool:
        """Ask before committing to a tier. Never raises, so a caller can choose
        to degrade *before* starting work rather than half way through it."""
        try:
            self.load()
        except ModelUnavailable:
            return False
        return True

    def extract(self, text: str, labels: list[str], *, threshold: float = 0.5) -> list[Span]:
        """Raises ModelUnavailable if the model will not load — callers degrade
        explicitly. Empty text short-circuits before the model is touched, so
        "no entities" for an empty document does not depend on the model being
        installed."""
        if not text or not labels:
            return []

        model = self.load()
        raw = model.predict_entities(text, labels, threshold=threshold)
        return [span for span in (self._to_span(text, item) for item in raw) if span is not None]

    @staticmethod
    def _to_span(text: str, item: dict[str, Any]) -> Span | None:
        """Drop anything whose offsets do not agree with the source. GLiNER
        returns both the matched string and its offsets, so they check each other
        for free — a span whose offsets point elsewhere would redact the wrong
        text (the bug Gate 1 stops, caught a layer earlier). The range is checked
        before the slice, because Python slicing lets three broken spans past
        `text[start:end] == matched`: a negative `start`, `start > end` (yields
        `""`), and an `end` past the string (clamps)."""
        try:
            start = int(item["start"])
            end = int(item["end"])
            matched = str(item["text"])
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 <= start < end <= len(text):
            return None
        if text[start:end] != matched:
            return None
        return Span(
            text=matched,
            label=str(item.get("label", "")),
            start=start,
            end=end,
            score=float(item.get("score", 0.0)),
        )


class DisabledNER:
    """`GLINER_ENABLED=false` as an object, not an `if`. Substituting it for a
    real client keeps "tier 2 is off" one configuration choice instead of a
    branch at every call site, and `enabled` is False for anyone who asks."""

    enabled = False
    is_available = False

    def extract(self, text: str, labels: list[str], *, threshold: float = 0.5) -> list[Span]:
        return []


__all__ = [
    "DisabledNER",
    "GLiNERClient",
    "ModelUnavailable",
    "NERClient",
    "Span",
]
