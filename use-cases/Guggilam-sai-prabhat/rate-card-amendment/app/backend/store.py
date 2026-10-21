"""In-process storage for runs, cases, and idempotency keys.

This app runs as a single FastAPI process against a small synthetic fixture
corpus — there is no need for a database. `AppStore` is a plain in-memory
store keyed by run_id/case_id, plus an idempotency-key table so repeated
submissions of the same client-generated key return the original response
without re-running analysis or re-calling SuperDocs.

Not safe for multi-process deployment; documented as a known limitation in
the README. A future swap to SQLite/Postgres would only touch this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.amendment_case import AmendmentCase


@dataclass
class Run:
    run_id: str
    dry_run: bool
    proposed_effective_date: str
    template_name: str
    cases: dict[str, AmendmentCase] = field(default_factory=dict)


class AppStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._idempotency: dict[str, Any] = {}

    # --- runs -----------------------------------------------------------
    def save_run(self, run: Run) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[Run]:
        return self._runs.get(run_id)

    # --- idempotency ------------------------------------------------------
    def get_idempotent_response(self, key: str) -> Optional[Any]:
        return self._idempotency.get(key)

    def save_idempotent_response(self, key: str, response: Any) -> None:
        self._idempotency[key] = response

    # --- test/debug -------------------------------------------------------
    def reset(self) -> None:
        self._runs.clear()
        self._idempotency.clear()


store = AppStore()
