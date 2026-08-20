"""Human-in-the-loop review orchestration.

Implements the exact poll/approve loop documented at
docs.superdocs.app/guides/human-in-the-loop, including the two flavours of
`awaiting_approval` (change review vs. large-edit `continue_prompt`) and the
required-top-level-`approved` footgun called out in that guide.

Two operating modes:
- interactive (default when running the CLI in a terminal): print each proposed
  change and prompt the operator y/n/(f)eedback.
- auto-approve (`--auto-approve`, used for the demo script and in tests): approve
  everything automatically, still going through the same real approve/deny call so
  the Review surface is genuinely exercised, not skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .client import SuperDocsClient


class ContinuePromptNotHandled(RuntimeError):
    pass


@dataclass
class ReviewDecision:
    change_id: str
    approved: bool
    feedback: str | None = None


ApprovalCallback = Callable[[list[dict]], list[ReviewDecision]]


def auto_approve_all(pending_changes: list[dict]) -> list[ReviewDecision]:
    return [ReviewDecision(change_id=c["change_id"], approved=True) for c in pending_changes]


def interactive_prompt(pending_changes: list[dict]) -> list[ReviewDecision]:  # pragma: no cover - interactive
    decisions = []
    for change in pending_changes:
        print(f"\n--- Proposed change {change['change_id']} ({change['operation']}) ---")
        print(f"Why: {change.get('ai_explanation', 'n/a')}")
        if change.get("old_html"):
            print(f"OLD: {change['old_html'][:200]}")
        if change.get("new_html"):
            print(f"NEW: {change['new_html'][:200]}")
        answer = input("Approve? [y/n/f=deny with feedback] ").strip().lower()
        if answer == "y":
            decisions.append(ReviewDecision(change["change_id"], True))
        elif answer == "f":
            fb = input("Feedback for the AI: ").strip()
            decisions.append(ReviewDecision(change["change_id"], False, feedback=fb))
        else:
            decisions.append(ReviewDecision(change["change_id"], False))
    return decisions


def run_reviewed_chat(
    client: SuperDocsClient,
    session_id: str,
    message: str,
    approval_callback: ApprovalCallback,
    max_rounds: int = 5,
    **chat_kwargs,
) -> dict:
    """Runs one chat_async turn through to completion, handling `awaiting_approval`
    rounds via approval_callback. Returns the final job dict (status == completed).

    Raises ContinuePromptNotHandled if a large-edit continue_prompt pause is hit --
    this project's documents are small enough that this should never trigger; if it
    does, that's a signal the transcript/brief input was unexpectedly large, and we
    fail loudly rather than guessing whether to continue.
    """
    client.usage.check_budget("chat_async")
    started = client.chat_async(session_id, message, approval_mode="ask_every_time", **chat_kwargs)
    job_id = started["job_id"]

    for _ in range(max_rounds):
        job = client.wait_for_job(job_id, stop_statuses=("completed", "failed", "cancelled", "awaiting_approval"))
        status = job.get("status")

        if status == "completed":
            return job
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"Chat job {job_id} ended with status={status}: {job.get('error')}")

        # awaiting_approval -- branch on awaiting_kind first (documented footgun)
        awaiting_kind = job.get("metadata", {}).get("awaiting_kind")
        if awaiting_kind == "continue_prompt":
            raise ContinuePromptNotHandled(
                f"Job {job_id} paused on a large-edit continue_prompt, which this "
                "project does not expect for debrief/brief-sized documents. Refusing "
                "to guess continue=true/false automatically."
            )

        pending = job.get("metadata", {}).get("pending_changes", [])
        decisions = approval_callback(pending)
        # Group into one batch call with the required top-level `approved` field.
        client.approve_change(
            session_id,
            job_id,
            approved=True,  # required top-level default; per-change values below win
            changes=[
                {"change_id": d.change_id, "approved": d.approved, **({"feedback": d.feedback} if d.feedback else {})}
                for d in decisions
            ],
        )

    raise RuntimeError(f"Chat job {job_id} did not complete within {max_rounds} approval rounds")
