"""
@file: backend/services/llm_gate.py
@description: Single decision point for "can we use the LLM, and what do we do if not".
    Wraps every Groq call so the choice between the model path and the heuristic path is
    made in one place with one policy, rather than each node inventing its own handling
    of a missing key or an outage.
@flow: a node calls run_with_fallback() with an LLM coroutine and a heuristic callable
    -> if Groq is configured and reachable the LLM result is returned with degraded=False
    -> on MissingCredentialError or GroqUnavailable, and only when degraded analysis is
    permitted, the heuristic runs instead and returns degraded=True with caveats -> the
    node logs the decision and records the caveats so the digest can disclose them.
@dependencies:
    - backend.services.groq_client: the exceptions that trigger the fallback
    - backend.services.heuristics: the LLM-free implementations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.config import MissingCredentialError, settings
from backend.services.groq_client import (
    GroqBudgetError,
    GroqError,
    GroqQuotaExhausted,
    GroqUnavailable,
    LLMUsage,
)

logger = logging.getLogger(__name__)

# Circuit breaker. Once the token allowance is spent, every subsequent call fails the
# same way — so the first exhaustion trips the breaker and the rest of the run degrades
# without asking again. Without this, a 25-theme anonymize stage re-proved the same
# exhausted quota 25 times, turning a 40-conversation run into three hours of 429s.
_BREAKER: dict[str, Any] = {"open": False, "reason": "", "retry_after_s": None}


def breaker_is_open() -> bool:
    return bool(_BREAKER["open"])


def trip_breaker(reason: str, retry_after_s: float | None = None) -> None:
    if not _BREAKER["open"]:
        logger.warning(
            "LLM circuit breaker tripped — no further Groq calls this run: %s", reason
        )
    _BREAKER.update({"open": True, "reason": reason, "retry_after_s": retry_after_s})


def reset_breaker() -> None:
    """Clear the breaker. Called at the start of each run so a later run can try again."""
    _BREAKER.update({"open": False, "reason": "", "retry_after_s": None})


def breaker_reason() -> str:
    return str(_BREAKER["reason"])


@dataclass(slots=True)
class GatedResult:
    """Outcome of a gated call, carrying how it was produced."""

    data: Any
    usage: LLMUsage = field(default_factory=LLMUsage)
    degraded: bool = False
    reason: str = ""
    caveats: list[str] = field(default_factory=list)


def groq_available() -> bool:
    """Whether a Groq key is configured. Does not prove the service is reachable."""
    return bool(settings.groq_api_key)


async def run_with_fallback(
    stage: str,
    llm_call: Callable[[], Awaitable[tuple[Any, LLMUsage]]],
    heuristic_call: Callable[[], Any],
    *,
    degrade_on_budget_error: bool = False,
) -> GatedResult:
    """Run the LLM path, falling back to heuristics on unavailability.

    Only unavailability triggers the fallback — a missing key, an outage, exhausted
    credits. A GroqError caused by malformed output is re-raised so the node's normal
    retry can handle it, because silently degrading on a transient parse failure would
    quietly lower quality for a problem that would have fixed itself.

    `degrade_on_budget_error` is opt-in for the callers whose LLM contribution is a label
    or a parse rather than the analysis itself — theme naming, reading a prior digest.
    Those have a real heuristic equivalent and losing them costs presentation, not
    findings. It is deliberately off by default: for classify and extract the right
    answer to a request that will not fit is to split it, and degrading instead would
    trade the model's output for keyword output over a problem that has a proper fix.
    """
    if not groq_available():
        if not settings.allow_degraded_analysis:
            raise MissingCredentialError("GROQ_API_KEY", f"the {stage} stage")
        return _degrade(
            stage, heuristic_call, "GROQ_API_KEY is not configured"
        )

    # Allowance already known to be spent — skip the call entirely.
    if breaker_is_open():
        if not settings.allow_degraded_analysis:
            raise GroqQuotaExhausted(breaker_reason())
        return _degrade(stage, heuristic_call, breaker_reason())

    try:
        data, usage = await llm_call()
        return GatedResult(data=data, usage=usage, degraded=False)

    except MissingCredentialError as exc:
        if not settings.allow_degraded_analysis:
            raise
        return _degrade(stage, heuristic_call, str(exc))

    except GroqQuotaExhausted as exc:
        # Trip the breaker so the remaining stages and batches do not each rediscover
        # this. One exhaustion is enough to know the rest will fail too.
        trip_breaker(str(exc), exc.retry_after_s)
        if not settings.allow_degraded_analysis:
            raise
        return _degrade(stage, heuristic_call, str(exc))

    except GroqUnavailable as exc:
        if not settings.allow_degraded_analysis:
            raise
        # Transient: an outage or a short burst limit already retried by the client.
        return _degrade(stage, heuristic_call, f"Groq unavailable: {exc}")

    except GroqBudgetError as exc:
        # The request and the provider's ceiling cannot both be satisfied. Retrying it
        # unchanged is guaranteed to fail the same way, so either the caller splits (the
        # default, for the stages that can) or it degrades here, with disclosure.
        if not degrade_on_budget_error:
            raise
        if not settings.allow_degraded_analysis:
            raise
        return _degrade(stage, heuristic_call, f"the request exceeded Groq's token "
                                               f"ceiling and could not be split: {exc}")

    except GroqError:
        # Malformed output, not unavailability. Let the node retry.
        raise


def _degrade(stage: str, heuristic_call: Callable[[], Any], reason: str) -> GatedResult:
    logger.warning("Stage %s degraded to heuristics: %s", stage, reason)
    result = heuristic_call()
    data = getattr(result, "data", result)
    caveats = list(getattr(result, "caveats", []))
    return GatedResult(
        data=data,
        usage=LLMUsage(),  # no tokens were spent
        degraded=True,
        reason=reason,
        caveats=caveats,
    )