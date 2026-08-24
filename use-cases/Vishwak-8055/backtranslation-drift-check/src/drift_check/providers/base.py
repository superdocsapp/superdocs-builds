"""Provider abstraction for back-translation + semantic assessment.

``TranslationAnalysisProvider`` is the one seam between the deterministic
pipeline and any LLM. Two concrete implementations exist:

- ``FixtureProvider`` (fixture.py): returns pre-recorded text. No network
  access, fully deterministic, used for the offline demo and the whole test
  suite. This is what "Offline tests MUST NOT require API credentials" means
  in practice.
- ``AnthropicProvider`` (anthropic_provider.py): calls the real Anthropic
  Messages API over HTTPS. Fully implemented and unit-tested against a mocked
  HTTP layer, but not exercised end-to-end in this environment because no
  API credentials are available — see LIMITATIONS.md #5.

Back-translation and semantic assessment are deliberately produced by a
*single* provider call (``analyze``) rather than two, so that the one LLM
round-trip a section genuinely requires also carries the semantic read. See
DECISIONS.md #7.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from drift_check.models import BackTranslationResult


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a usable result after retries."""


class TranslationAnalysisProvider(Protocol):
    """Back-translates a section and independently assesses whether it drifted.

    Deliberately does *not* take the deterministic signals as input: this
    provider's semantic read and the regex-based signals in
    ``drift_check.signals`` are two independent detection passes that are
    combined afterwards (see drift_engine.analyze_section_pair), not a
    pipeline where one primes the other. Independence is what makes
    corroboration between them meaningful.
    """

    name: str

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
        """Back-translate ``target_text`` to ``source_lang`` and assess drift against ``source_text``."""
        ...


T = TypeVar("T")


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.2,
    retryable: tuple[type[BaseException], ...] = (ProviderError,),
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Call ``fn`` with bounded exponential backoff + jitter.

    Returns ``(result, retry_count)``. Never loops unboundedly: after
    ``max_attempts`` failures the last exception is re-raised.
    """
    attempt = 0
    while True:
        try:
            return fn(), attempt
        except retryable:
            attempt += 1
            if attempt >= max_attempts:
                raise
            delay = base_delay_s * (2 ** (attempt - 1)) + random.uniform(0, base_delay_s)
            sleep(delay)
