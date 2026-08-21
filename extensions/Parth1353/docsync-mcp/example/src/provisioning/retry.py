"""Retry and dead-lettering for circuit provisioning jobs.

Part of a synthetic example service. No real company's code.
"""

from __future__ import annotations

# How many times a provisioning job is attempted before it is dead-lettered.
MAX_ATTEMPTS = 3

# How long to wait between attempts. Fixed, not exponential — the downstream
# carrier API rate-limits per minute, so backing off further does not help.
BACKOFF_SECONDS = 30


def should_retry(attempt: int, status: int) -> bool:
    if attempt >= MAX_ATTEMPTS:
        return False
    return status in (429, 502, 503, 504)
