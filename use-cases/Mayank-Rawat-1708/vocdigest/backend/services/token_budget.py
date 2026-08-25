"""
@file: backend/services/token_budget.py
@description: Keeps every Groq request inside the provider's real token ceiling. Groq
    counts the *requested* max_tokens against the per-minute allowance before a single
    token is generated, so a request's size has to be decided before it is sent, against
    a limit the provider publishes rather than one we assume. This module owns that
    arithmetic: it learns the limits from response headers, estimates prompt size, and
    decides how much completion budget a call may ask for.
@flow: GroqClient posts -> observe_headers() records x-ratelimit-limit-tokens /
    -remaining-tokens / -reset-tokens -> the next call asks budget_for_prompt() how much
    completion budget is left after its prompt -> a plan that does not fit is refused
    locally (no wasted HTTP call) so the caller can split the batch -> calibrate() feeds
    the response's real prompt_tokens back so the estimator self-corrects.
@dependencies:
    - backend.config.settings: bootstrap ceiling, headroom, floors
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

from backend.config import settings

logger = logging.getLogger(__name__)

# Characters per token. English prose runs ~4.0 for this tokeniser family; we start
# lower so the estimate errs high. The asymmetry is deliberate: over-estimating costs
# one extra (smaller) call, under-estimating costs a 413 that wastes the whole call and
# still consumes rate-limit budget. calibrate() tightens this from real usage numbers.
_DEFAULT_CHARS_PER_TOKEN = 3.2

# Per-message framing the API adds around each role/content pair.
_MESSAGE_OVERHEAD_TOKENS = 8


def _chars_per_token() -> float:
    """The ratio in force: the default, or a more pessimistic observed one."""
    observed = _OBSERVED.chars_per_token
    if observed is None:
        return _DEFAULT_CHARS_PER_TOKEN
    return min(_DEFAULT_CHARS_PER_TOKEN, observed)


def estimate_tokens(*texts: str) -> int:
    """Conservative prompt-token estimate for one or more messages."""
    ratio = _chars_per_token()
    total = 0
    for text in texts:
        if not text:
            continue
        total += math.ceil(len(text) / ratio) + _MESSAGE_OVERHEAD_TOKENS
    return total


# ---------------------------------------------------------------- rate limits

# Groq expresses reset windows as compact durations: "705ms", "1.5s", "27m21.6s",
# "2m". Parsed rather than pattern-matched on a single unit, because which unit appears
# depends on how much of the window is left.
_DURATION = re.compile(
    r"(?:(?P<h>[\d.]+)h)?(?:(?P<m>[\d.]+)m(?!s))?(?:(?P<s>[\d.]+)s)?(?:(?P<ms>[\d.]+)ms)?",
    re.IGNORECASE,
)

# Groq states the ceiling it enforced inside the 413 body:
#   "... tokens per minute (TPM): Limit 8000, Requested 9904 ..."
# That is a second, authoritative source for the limit, available exactly when we most
# need it — a request that was rejected for being too large.
_LIMIT_IN_ERROR = re.compile(
    r"Limit\s+(?P<limit>\d+)\s*,\s*Requested\s+(?P<requested>\d+)", re.IGNORECASE
)


def parse_duration(value: str | None) -> float | None:
    """Seconds from a Groq duration string, or None if unparseable."""
    if not value:
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    match = _DURATION.fullmatch(text)
    if not match or not any(match.groupdict().values()):
        return None
    parts = match.groupdict()
    seconds = 0.0
    if parts.get("h"):
        seconds += float(parts["h"]) * 3600
    if parts.get("m"):
        seconds += float(parts["m"]) * 60
    if parts.get("s"):
        seconds += float(parts["s"])
    if parts.get("ms"):
        seconds += float(parts["ms"]) / 1000
    return seconds


@dataclass(slots=True)
class RateLimitSnapshot:
    """What the provider last told us about our allowance."""

    limit_tokens: int | None = None
    remaining_tokens: int | None = None
    reset_tokens_s: float | None = None
    limit_requests: int | None = None
    remaining_requests: int | None = None
    reset_requests_s: float | None = None
    #: monotonic clock reading when this was captured, so staleness is measurable
    observed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit_tokens": self.limit_tokens,
            "remaining_tokens": self.remaining_tokens,
            "reset_tokens_s": self.reset_tokens_s,
            "limit_requests": self.limit_requests,
            "remaining_requests": self.remaining_requests,
            "age_s": None
            if self.observed_at is None
            else round(time.monotonic() - self.observed_at, 3),
        }


class _ObservedState:
    """Process-wide view of the provider's limits.

    Deliberately module-level: the allowance is per-API-key, so every client instance,
    every stage and every concurrent run share one budget. A per-client view would let
    four parallel anonymize calls each believe it had the whole ceiling to itself.
    """

    def __init__(self) -> None:
        self.snapshot = RateLimitSnapshot()
        self.chars_per_token: float | None = None

    def reset(self) -> None:
        self.snapshot = RateLimitSnapshot()
        self.chars_per_token = None


_OBSERVED = _ObservedState()


def reset_observed_limits() -> None:
    """Forget what we learned. Used by tests; never needed in a live process."""
    _OBSERVED.reset()


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def observe_headers(headers: Mapping[str, str]) -> RateLimitSnapshot:
    """Record the rate-limit headers from any response, success or error.

    Called on every response including 4xx/5xx: a rejected request still reports the
    allowance, and that is precisely the moment the numbers matter.
    """
    limit = _as_int(headers.get("x-ratelimit-limit-tokens"))
    remaining = _as_int(headers.get("x-ratelimit-remaining-tokens"))
    reset = parse_duration(headers.get("x-ratelimit-reset-tokens"))

    snapshot = RateLimitSnapshot(
        limit_tokens=limit if limit is not None else _OBSERVED.snapshot.limit_tokens,
        remaining_tokens=remaining,
        reset_tokens_s=reset,
        limit_requests=_as_int(headers.get("x-ratelimit-limit-requests")),
        remaining_requests=_as_int(headers.get("x-ratelimit-remaining-requests")),
        reset_requests_s=parse_duration(headers.get("x-ratelimit-reset-requests")),
        observed_at=time.monotonic(),
    )
    if limit is not None and limit != (_OBSERVED.snapshot.limit_tokens or limit):
        logger.info("Groq per-minute token limit is now %s (was %s)",
                    limit, _OBSERVED.snapshot.limit_tokens)
    _OBSERVED.snapshot = snapshot
    return snapshot


def note_limit_from_error(detail: str) -> int | None:
    """Learn the ceiling from a 413 body. Returns the limit it stated, if any."""
    match = _LIMIT_IN_ERROR.search(detail or "")
    if not match:
        return None
    limit = int(match.group("limit"))
    requested = int(match.group("requested"))
    logger.warning(
        "Groq rejected a request as too large: it enforced a %s-token ceiling and we "
        "asked for %s. Recording %s as the ceiling.", limit, requested, limit
    )
    _OBSERVED.snapshot.limit_tokens = limit
    # A rejected request generates nothing, but the window is clearly tight.
    _OBSERVED.snapshot.observed_at = time.monotonic()
    return limit


def calibrate(prompt_chars: int, actual_prompt_tokens: int) -> None:
    """Tighten the chars-per-token ratio from a real response.

    Keeps the most pessimistic ratio seen this process. Content varies — a batch of
    identifier-heavy support tickets tokenises far worse than prose — and the estimate
    must hold for the worst batch, not the average one.
    """
    if actual_prompt_tokens <= 0 or prompt_chars <= 0:
        return
    ratio = prompt_chars / actual_prompt_tokens
    current = _OBSERVED.chars_per_token
    if current is None or ratio < current:
        _OBSERVED.chars_per_token = ratio
        if ratio < _DEFAULT_CHARS_PER_TOKEN:
            logger.debug(
                "Prompt token estimate tightened to %.2f chars/token from a real "
                "response (%s chars -> %s tokens)",
                ratio, prompt_chars, actual_prompt_tokens,
            )


def token_ceiling() -> int:
    """Tokens one request may total (prompt + requested completion).

    The provider's own header is authoritative. Until a response has been seen this
    process, GROQ_TPM_LIMIT is used as a bootstrap — it exists only so the very first
    request of a process is conservative rather than unbounded, and it is replaced by
    the observed value as soon as any response (including a rejection) arrives.
    """
    observed = _OBSERVED.snapshot.limit_tokens
    if observed and observed > 0:
        return observed
    return max(settings.groq_tpm_limit, 1024)


def current_limits() -> RateLimitSnapshot:
    return _OBSERVED.snapshot


@dataclass(slots=True)
class BudgetPlan:
    """The decision about one request's size."""

    #: completion budget the request may ask for
    max_tokens: int
    #: estimated prompt tokens this plan was computed against
    prompt_tokens: int
    #: ceiling in force
    ceiling: int
    #: smallest completion budget the caller said it could work with
    floor: int
    fits: bool
    reason: str = ""

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.max_tokens


def budget_for_prompt(
    prompt_tokens: int, requested: int, *, floor: int
) -> BudgetPlan:
    """How much completion budget this prompt can be given.

    `floor` is the caller's own minimum — the smallest completion budget in which its
    answer could actually be produced. A plan below the floor does not "fit": returning
    a too-small budget anyway is what produces an empty completion, which the provider
    then reports as a JSON validation failure for output that was never generated.
    """
    ceiling = token_ceiling()
    headroom = max(settings.groq_tpm_headroom, 0)
    available = ceiling - headroom - prompt_tokens
    floor = max(int(floor), 1)

    if available < floor:
        return BudgetPlan(
            max_tokens=max(available, 0),
            prompt_tokens=prompt_tokens,
            ceiling=ceiling,
            floor=floor,
            fits=False,
            reason=(
                f"a {prompt_tokens}-token prompt plus the {floor} completion tokens its "
                f"answer needs is {prompt_tokens + floor} tokens, over the "
                f"{ceiling}-token per-request ceiling "
                f"(minus {headroom} reserved as headroom)"
            ),
        )

    return BudgetPlan(
        max_tokens=max(min(int(requested), available), floor),
        prompt_tokens=prompt_tokens,
        ceiling=ceiling,
        floor=floor,
        fits=True,
    )


def fit_untrusted_excerpt(
    text: str, *, fixed_prompt: str, answer_tokens: int
) -> tuple[str, str]:
    """Trim untrusted text to what will fit alongside its answer.

    Returns (excerpt, note). The note is empty when nothing was dropped, and otherwise
    says how much was read — a silently truncated source is exactly the kind of quiet
    quality loss the rest of this system refuses to make.

    A fixed character cap cannot do this job: it is a guess about tokens made in the
    wrong unit, and a cap generous enough to be useful on a large tier leaves no room for
    the answer on a small one.
    """
    ceiling = token_ceiling()
    headroom = max(settings.groq_tpm_headroom, 0)
    reserve = (
        settings.groq_reasoning_reserve_tokens
        if "gpt-oss" in settings.groq_model
        else 0
    )
    allowance = ceiling - headroom - answer_tokens - reserve - estimate_tokens(
        fixed_prompt
    )
    if allowance <= 0:
        # Nothing fits. Hand back a token-sized crumb; the caller's budget check will
        # refuse the request and it can degrade with a clear reason.
        return text[:200], (
            f"no room for any of the source text under the {ceiling}-token ceiling"
        )

    max_chars = int(allowance * _chars_per_token())
    if len(text) <= max_chars:
        return text, ""
    return text[:max_chars], (
        f"read the first {max_chars:,} of {len(text):,} characters — the rest does not "
        f"fit under the {ceiling}-token per-request ceiling alongside the answer"
    )


def wait_for_tokens(needed: int) -> float:
    """Seconds to wait so `needed` tokens are available, per the last snapshot.

    Spending the window down to zero and then eating a 429 costs more wall clock than
    pausing for the reset, so the remaining-token header is treated as a spend limit
    rather than as trivia.
    """
    snapshot = _OBSERVED.snapshot
    remaining = snapshot.remaining_tokens
    if remaining is None or snapshot.observed_at is None:
        return 0.0

    reset = snapshot.reset_tokens_s
    age = time.monotonic() - snapshot.observed_at
    if reset is not None and age >= reset:
        # The window has already rolled over since we looked; the allowance is fresh.
        return 0.0
    if remaining >= needed:
        return 0.0

    wait = (reset if reset is not None else 60.0) - age
    return max(wait, 0.0)
