"""Task 2's top-level orchestration -- ties drafter/analysis.py, /synthesize.py,
and /publish.py together. Split into two entry points, deliberately not one
long function, mirroring pipeline/runner.py's own "run stops at a
human-reviewable point" shape:

- draft_memo(): reads a contract, runs analysis + synthesis, and returns
  the fully-verified, fully-rendered memo -- entirely LOCAL, no SuperDocs
  call yet. This is the part that's cheap and safe to run repeatedly while
  iterating (and the part covered by tests/test_drafter_integration.py's
  real-fixture, real-difference proof).
- publish_memo_to_superdocs(): takes that already-built state and pushes
  it through SuperDocs's real API (drafter/publish.py). Kept as a genuinely
  separate call so a caller can inspect/log the memo locally before ever
  spending an API operation on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from core.llm import LLMClient
from core.logging import bind_run_id, clear_run_context, get_logger
from core.superdocs_client import SuperDocsClient
from drafter.analysis import analyze_contract
from drafter.publish import export_memo, poll_until_resolved, start_memo_authoring_job
from drafter.state import DrafterState
from drafter.synthesize import synthesize_memo

logger = get_logger(__name__)


def initial_state(run_id: str, contract_path: str, contract_text: str, contract_filename: str) -> DrafterState:
    return {
        "run_id": run_id,
        "contract_path": contract_path,
        "contract_text": contract_text,
        "contract_filename": contract_filename,
        "analysis": {
            "contract_filename": contract_filename,
            "performance_obligations": [],
            "price_allocations": [],
            "timing_conclusions": [],
        },
        "judgement_notes": [],
        "memo_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }


def draft_memo(contract_path: str, llm: LLMClient, run_id: str | None = None) -> DrafterState:
    """Reads the contract, runs analyze_contract + synthesize_memo. No
    SuperDocs call -- see module docstring for why that's a separate step."""
    run_id = run_id or str(uuid4())
    bind_run_id(run_id)
    try:
        path = Path(contract_path)
        contract_text = path.read_text(encoding="utf-8")
        state = initial_state(run_id, str(path), contract_text, path.name)

        state.update(analyze_contract(state, llm))  # type: ignore[typeddict-item]
        state.update(synthesize_memo(state))  # type: ignore[typeddict-item]

        logger.info(
            "memo_drafted",
            contract_filename=state["contract_filename"],
            obligation_count=len(state["analysis"]["performance_obligations"]),
        )
        return state
    finally:
        clear_run_context()


def publish_memo_to_superdocs(
    state: DrafterState,
    client: SuperDocsClient,
    auto_approve: bool = False,
    export_format: str = "docx",
) -> dict[str, Any]:
    """Pushes an already-drafted memo through SuperDocs (see drafter/
    publish.py for the full HITL flow and the trust-boundary rationale).
    Returns a status dict; if the job is still awaiting_approval (auto_
    approve=False and there were pending changes), returns that state
    instead of exporting -- exporting an unresolved job would export a
    not-yet-finished document."""
    bind_run_id(state["run_id"])
    try:
        session_id = f"revrec-{state['run_id']}"
        job = start_memo_authoring_job(client, session_id, state["memo_html"])
        job_id = job["job_id"]

        resolved = poll_until_resolved(client, job_id, session_id, auto_approve=auto_approve)
        if resolved.get("status") != "completed":
            return {
                "status": resolved.get("status"),
                "job_id": job_id,
                "session_id": session_id,
                "pending_changes": resolved.get("metadata", {}).get("pending_changes", []),
            }

        export_result = export_memo(client, session_id, format=export_format)
        return {
            "status": "completed",
            "job_id": job_id,
            "session_id": session_id,
            "export": export_result,
        }
    finally:
        clear_run_context()
