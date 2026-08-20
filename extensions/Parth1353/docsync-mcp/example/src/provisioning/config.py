"""Service configuration.

Part of a synthetic example service. No real company's code.
"""

from __future__ import annotations

# Timeout for a single call to the carrier provisioning API.
REQUEST_TIMEOUT_SECONDS = 30

# Bandwidth assumed when an order does not name one.
DEFAULT_BANDWIDTH_MBPS = 1000

# Where jobs go when they have exhausted their attempts.
DEAD_LETTER_TOPIC = "provisioning.dead-letter"

# Per-tenant API rate limit, requests per minute.
RATE_LIMIT_PER_MINUTE = 1000
