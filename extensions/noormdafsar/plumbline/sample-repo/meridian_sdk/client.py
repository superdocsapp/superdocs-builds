"""Meridian SDK -- a fabricated client library, used to demonstrate Plumbline.

Nothing here talks to a real service. It exists so there is a realistic public
surface whose documentation can drift away from it.
"""

from __future__ import annotations

DEFAULT_TIMEOUT = 45
MAX_PAGE_SIZE = 500
DEFAULT_REGION = "eu-west-1"
RETRY_BACKOFF_SECONDS = 2.0


class MeridianError(Exception):
    """Base class for everything this SDK raises."""


class RateLimited(MeridianError):
    """Raised when the service asks the caller to slow down."""


class NotFound(MeridianError):
    """Raised when a requested record does not exist."""


class Client:
    """A client for the Meridian ledger service."""

    def __init__(
        self,
        api_key: str,
        *,
        region: str = DEFAULT_REGION,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.region = region
        self.timeout = timeout
        self.max_retries = max_retries

    def list_ledgers(
        self,
        *,
        page_size: int = 100,
        cursor: str | None = None,
        include_archived: bool = False,
    ) -> list[dict]:
        """Return one page of ledgers.

        Ledgers come back newest first.
        """
        if page_size > MAX_PAGE_SIZE:
            raise ValueError(f"page_size cannot exceed {MAX_PAGE_SIZE}")
        return []

    def get_ledger(self, ledger_id: str) -> dict:
        """Fetch a single ledger by id."""
        if not ledger_id:
            raise ValueError("ledger_id is required")
        raise NotFound(f"no ledger {ledger_id}")

    def post_entry(
        self,
        ledger_id: str,
        amount_minor: int,
        *,
        currency: str = "EUR",
        idempotency_key: str | None = None,
    ) -> dict:
        """Append an entry to a ledger.

        Amounts are in minor units: 1250 means 12.50.
        """
        if amount_minor == 0:
            raise ValueError("amount_minor must not be zero")
        return {"id": "ent_demo", "ledger_id": ledger_id, "amount_minor": amount_minor}

    def close_ledger(self, ledger_id: str, *, reason: str) -> bool:
        """Close a ledger. Returns True when the ledger moved to closed."""
        if not reason:
            raise ValueError("a reason is required to close a ledger")
        return True
