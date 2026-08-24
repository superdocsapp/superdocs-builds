"""Offline, credential-free provider backed by pre-recorded fixture data.

Used for: the whole test suite, and the flagship/second-document demos when
no live API key is configured (see LIMITATIONS.md #5). Back-translation text
is pre-authored (representing what a competent human or LLM back-translator
would produce); semantic assessments default to "no additional drift beyond
what the deterministic layer already found" unless overridden — used for the
one demo section (Section 12 of the flagship document) engineered to be
invisible to every regex detector and catchable only by a semantic read.

This is disclosed, not hidden: the report and CLI both label results
produced under this provider as fixture-sourced.

JSON file format (``from_json_file``) accepts either shape:

- Flat — ``{"1": "back-translation text", "2": "...", ...}`` — no semantic
  overrides, used by fixtures that don't need any (e.g. the second document).
- Structured — ``{"back_translations": {...}, "semantic_overrides": {"12":
  {"has_drift": true, "category": "...", "severity": "...", "confidence":
  0.85, "rationale": "..."}}}`` — used by the flagship fixture, so that
  running it through the CLI alone (not just the Python demo-provider
  helper) reproduces the same result, including the semantic-only finding.
"""

from __future__ import annotations

import json
from pathlib import Path

from drift_check.models import BackTranslationResult, DriftCategory, SemanticAssessment, Severity
from drift_check.providers.base import ProviderError


def _parse_semantic_override(raw: dict[str, object]) -> SemanticAssessment:
    category_raw = raw.get("category")
    severity_raw = raw.get("severity")
    return SemanticAssessment(
        has_drift=bool(raw.get("has_drift", False)),
        category=DriftCategory(category_raw) if category_raw else None,
        rationale=str(raw.get("rationale", "")),
        confidence=float(raw.get("confidence", 0.5)),  # type: ignore[arg-type]
        severity_hint=Severity(severity_raw) if severity_raw else None,
    )


class FixtureProvider:
    name = "fixture"

    def __init__(
        self,
        back_translations: dict[int, str],
        *,
        semantic_overrides: dict[int, SemanticAssessment] | None = None,
        model: str = "fixture-v1",
        fail_first_n_calls_for_index: dict[int, int] | None = None,
    ) -> None:
        self._back_translations = back_translations
        self._semantic_overrides = semantic_overrides or {}
        self._model = model
        self._fail_budget = dict(fail_first_n_calls_for_index or {})
        self.call_log: list[int] = []

    @classmethod
    def from_json_file(cls, path: str | Path, **kwargs: object) -> FixtureProvider:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "back_translations" in data:
            back_translations = {int(k): v for k, v in data["back_translations"].items()}
            overrides = {int(k): _parse_semantic_override(v) for k, v in data.get("semantic_overrides", {}).items()}
            kwargs.setdefault("semantic_overrides", overrides)
        else:
            back_translations = {int(k): v for k, v in data.items()}
        return cls(back_translations, **kwargs)  # type: ignore[arg-type]

    def analyze(
        self,
        *,
        target_text: str,
        source_text: str,
        target_section_id: str,
        section_index: int,
        source_lang: str,
        target_lang: str,
    ) -> BackTranslationResult:
        self.call_log.append(section_index)

        remaining_failures = self._fail_budget.get(section_index, 0)
        if remaining_failures > 0:
            self._fail_budget[section_index] = remaining_failures - 1
            raise ProviderError(f"fixture: simulated transient failure for section index {section_index}")

        if section_index not in self._back_translations:
            raise ProviderError(f"fixture: no back-translation recorded for section index {section_index}")

        text = self._back_translations[section_index]
        assessment = self._semantic_overrides.get(section_index)
        if assessment is None:
            assessment = SemanticAssessment(
                has_drift=False,
                category=None,
                rationale=(
                    "No additional semantic drift beyond the deterministic signals "
                    "for this section (fixture default)."
                ),
                confidence=0.9,
            )

        return BackTranslationResult(
            target_section_id=target_section_id,
            text=text,
            provider=self.name,
            model=self._model,
            latency_ms=0.0,
            semantic_assessment=assessment,
            usage=None,
            retries=0,
        )
