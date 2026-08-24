"""Idempotency and safe-retry middleware for SuperDocs document operations.

Built for the SuperDocs open task list card "Idempotency and safe-retry
middleware" (p322, band S3). The written specification is SPEC.md; the
decision table is policy.json; the cross-language contract is vectors.json.
"""

from idem.policy import Backoff, MalformedPolicy, Policy, Rule
from idem.runner import (
    Idempotent,
    OutcomeUnknown,
    RetriesExhausted,
    TerminalFailure,
    UnknownPolicy,
    Verdict,
)
from idem.store import Record, Store

__all__ = [
    "Idempotent",
    "UnknownPolicy",
    "Verdict",
    "OutcomeUnknown",
    "TerminalFailure",
    "RetriesExhausted",
    "Policy",
    "Rule",
    "Backoff",
    "MalformedPolicy",
    "Store",
    "Record",
]
__version__ = "1.0.0"
