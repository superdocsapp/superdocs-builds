"""
@file: backend/services/batching.py
@description: Runs one indexed-JSON extraction over a list of records, splitting the
    batch whenever the request and the provider's token ceiling cannot both be
    satisfied. Exists because "how many records fit in one call" is not a constant: it
    depends on how long those particular records are, how much allowance is left in the
    current minute, and how much JSON the answer needs. A fixed batch size can only be
    wrong in one of two directions, and both directions produce an error about something
    other than size — 413 "request too large" or 400 "failed to validate JSON".
@flow: indexed_json_call() estimates the answer size for a batch -> asks the client for
    it -> the client either sends it or refuses locally -> on any budget error the batch
    is halved and each half retried independently -> per-record results are merged,
    keyed by their position in the ORIGINAL list so the caller needs no remapping.
@dependencies:
    - backend.services.groq_client: the client and its typed budget errors
    - backend.services.token_budget: the ceiling arithmetic behind the local refusal
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from backend.services.groq_client import (
    GroqBudgetError,
    GroqClient,
    GroqTruncatedOutput,
    LLMUsage,
)

logger = logging.getLogger(__name__)

# Completion tokens to leave for the JSON scaffolding around the per-record objects.
_ENVELOPE_TOKENS = 96


@dataclass(slots=True)
class BatchOutcome:
    """What one indexed-JSON extraction produced."""

    #: record index (position in the list passed in) -> that record's object
    results: dict[int, dict[str, Any]] = field(default_factory=dict)
    usage: LLMUsage = field(default_factory=LLMUsage)
    #: how many requests were actually sent
    calls: int = 0
    #: how many times a batch had to be halved
    splits: int = 0
    #: sizes of the sub-batches that were sent, largest first
    sent_sizes: list[int] = field(default_factory=list)


async def indexed_json_call(
    groq: GroqClient,
    *,
    system: str,
    instruction: Callable[[int], str],
    records: Sequence[str],
    per_record_output_tokens: int,
    max_output_tokens: int,
    results_key: str = "results",
) -> BatchOutcome:
    """Extract one JSON object per record, splitting the batch as the budget requires.

    Record markers carry each record's index in the ORIGINAL sequence, so a split does
    not renumber anything: the model echoes the index it was shown, and the caller reads
    results straight back against its own list. Renumbering per sub-batch is the obvious
    alternative and the reason to avoid it is that an off-by-one there silently attaches
    one customer's facts to another customer's conversation.
    """
    outcome = BatchOutcome()
    if not records:
        return outcome

    async def _run(lo: int, hi: int) -> None:
        size = hi - lo
        body = "\n\n".join(f"[{i}] {records[i]}" for i in range(lo, hi))
        # The answer needs room for every record it must describe. This is the floor the
        # client enforces: a smaller budget does not yield a shorter answer, it yields a
        # truncated one, which is no answer at all.
        needed = per_record_output_tokens * size + _ENVELOPE_TOKENS

        try:
            payload, usage, _ = await groq.complete_json(
                system,
                instruction(size),
                untrusted_content=body,
                max_tokens=min(needed, max_output_tokens),
                min_completion_tokens=needed,
            )
        except GroqBudgetError as exc:
            # A rejected request may still have been billed for the tokens it burned
            # producing nothing. Count them before deciding what to do.
            if exc.usage is not None:
                outcome.usage.merge(exc.usage)
            if size <= 1:
                if isinstance(exc, GroqTruncatedOutput):
                    # A single record whose answer did not fit. One retry with double the
                    # room, since there is nothing left to split.
                    payload, usage, _ = await groq.complete_json(
                        system,
                        instruction(size),
                        untrusted_content=body,
                        max_tokens=min(needed * 2, max_output_tokens),
                        min_completion_tokens=needed,
                    )
                    _absorb(outcome, payload, usage, size, results_key)
                    return
                raise
            mid = lo + size // 2
            outcome.splits += 1
            logger.info(
                "Splitting a %d-record batch into %d + %d: %s",
                size, mid - lo, hi - mid, exc,
            )
            await _run(lo, mid)
            await _run(mid, hi)
            return

        _absorb(outcome, payload, usage, size, results_key)

    await _run(0, len(records))
    outcome.sent_sizes.sort(reverse=True)
    return outcome


def _absorb(
    outcome: BatchOutcome,
    payload: Any,
    usage: LLMUsage,
    size: int,
    results_key: str,
) -> None:
    outcome.usage.merge(usage)
    outcome.calls += 1
    outcome.sent_sizes.append(size)
    if not isinstance(payload, dict):
        return
    for item in payload.get(results_key) or []:
        try:
            outcome.results[int(item["index"])] = item
        except (KeyError, TypeError, ValueError):
            continue
