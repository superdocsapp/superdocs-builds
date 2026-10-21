"""Task 2.2's top-level orchestration -- ties close_package/schedule.py,
/audit_trail.py, and /assemble.py together on top of Task 2's already-
proven engine (drafter/). Split into two entry points, the same shape as
drafter/runner.py, for the same reason:

- build_close_package(): reuses drafter.runner.draft_memo() to get an
  already-analyzed, already-verified, already-rendered memo, then runs
  the three Task 2.2-specific stages (extract_schedule_facts,
  compute_schedule_entries, build_audit_trail, assemble_package) on top
  of it. Entirely LOCAL, no SuperDocs call yet -- cheap and safe to run
  repeatedly while iterating.
- publish_package_to_superdocs(): pushes the assembled package_html
  through SuperDocs's real API, reusing drafter/publish.py's already-
  proven HITL flow (start_memo_authoring_job/poll_until_resolved/
  export_memo) verbatim -- the trust boundary and the auto-approve
  safety logic documented there apply identically to a close package as
  to a plain memo; nothing about publishing a package changes SuperDocs's
  role as authoring/delivery product, not a second source of judgement.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from close_package.assemble import assemble_package
from close_package.audit_trail import build_audit_trail
from close_package.schedule import compute_schedule_entries, extract_schedule_facts
from close_package.state import ClosePackageState
from core.llm import LLMClient
from core.logging import bind_run_id, clear_run_context, get_logger
from core.superdocs_client import SuperDocsClient
from drafter.publish import export_memo, poll_until_resolved, start_memo_authoring_job
from drafter.runner import draft_memo

logger = get_logger(__name__)


def build_close_package(contract_path: str, llm: LLMClient, run_id: str | None = None) -> ClosePackageState:
    """Reads the contract, runs Task 2's full draft_memo() (analysis +
    synthesis), then runs Task 2.2's schedule extraction + computation +
    audit trail + assembly on top of it. No SuperDocs call -- see module
    docstring for why that's a separate step."""
    run_id = run_id or str(uuid4())
    bind_run_id(run_id)
    try:
        memo_state = draft_memo(contract_path, llm, run_id=run_id)

        state: ClosePackageState = {
            "run_id": run_id,
            "memo_state": memo_state,
            "schedule": {
                "contract_filename": memo_state["contract_filename"],
                "schedule_facts": [],
                "entries": [],
            },
            "audit_trail": [],
            "package_html": "",
            "session_id": "",
            "job_id": "",
            "export_result": {},
            "stage_log": memo_state["stage_log"],
        }

        state.update(extract_schedule_facts(state, llm))  # type: ignore[typeddict-item]
        state.update(compute_schedule_entries(state))  # type: ignore[typeddict-item]
        state.update(build_audit_trail(state))  # type: ignore[typeddict-item]
        state.update(assemble_package(state))  # type: ignore[typeddict-item]

        logger.info(
            "close_package_built",
            contract_filename=memo_state["contract_filename"],
            schedule_entry_count=len(state["schedule"]["entries"]),
            audit_trail_entry_count=len(state["audit_trail"]),
        )
        return state
    finally:
        clear_run_context()


def publish_package_to_superdocs(
    state: ClosePackageState,
    client: SuperDocsClient,
    auto_approve: bool = False,
    export_format: str = "docx",
) -> dict[str, Any]:
    """Pushes an already-assembled close package through SuperDocs,
    reusing drafter/publish.py's HITL flow verbatim -- see that module's
    docstring for the full trust-boundary rationale, which applies
    identically here. Returns a status dict; if the job is still
    awaiting_approval (auto_approve=False and there were pending
    changes), returns that state instead of exporting -- exporting an
    unresolved job would export a not-yet-finished document."""
    bind_run_id(state["run_id"])
    try:
        session_id = f"closepkg-{state['run_id']}"
        job = start_memo_authoring_job(client, session_id, state["package_html"])
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
