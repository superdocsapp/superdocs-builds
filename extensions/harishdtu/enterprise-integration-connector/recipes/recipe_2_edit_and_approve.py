"""
RECIPE 2 — Edit a document and obtain human approval.

Flow (matches the brief exactly):
    existing document
    -> edit_by_instruction (async, approval_mode='ask_every_time')
    -> async job
    -> poll (JobWorker stops at 'awaiting_approval', which is a terminal
       poll state -- see worker.py's _TERMINAL_STATUSES -- so the recipe
       is notified the moment there's something for a human to review,
       not after some arbitrary further wait)
    -> expose pending changes (via the awaiting_approval callback payload)
    -> [human/platform reviews, decides per item -- happens outside this
       recipe, on the platform side, potentially minutes or hours later]
    -> submit_for_approval (item-level: some approved, some rejected)
    -> resume/poll again (a fresh background poll to the next terminal state)
    -> completed
    -> callback

This recipe is necessarily two entry points, not one function: a real
enterprise recipe can't hold a worker thread open waiting for a human to
click "approve" in a UI, possibly hours later. `start_edit_and_await_review`
returns as soon as there's something to review (or the edit auto-completed
with no changes needing approval); `submit_review_and_resume` is a second,
independent call the platform makes once it has collected the human's
decisions -- demonstrating item-level approve/reject genuinely round-tripping
through the connector, not just being modeled in a schema.
"""
from __future__ import annotations

from dataclasses import dataclass

from connector.callbacks import CallbackDispatcher
from connector.http_client import SuperDocsHTTPClient
from connector.operations.edit_by_instruction import edit_by_instruction
from connector.operations.submit_for_approval import submit_for_approval
from connector.worker import JobWorker
from schemas.approval import ApprovalInput, ChangeDecision
from schemas.common import ApprovalMode
from schemas.edit_by_instruction import EditByInstructionInput


@dataclass
class EditAndAwaitReviewInput:
    session_id: str
    instruction: str
    callback_dispatcher: CallbackDispatcher
    document_html: str | None = None


@dataclass
class EditAndAwaitReviewOutput:
    operation_id: str
    job_id: str | None
    session_id: str
    status: str


async def start_edit_and_await_review(
    client: SuperDocsHTTPClient, worker: JobWorker, recipe_input: EditAndAwaitReviewInput
) -> EditAndAwaitReviewOutput:
    result = await edit_by_instruction(client, EditByInstructionInput(
        session_id=recipe_input.session_id,
        instruction=recipe_input.instruction,
        document_html=recipe_input.document_html,
        approval_mode=ApprovalMode.ask_every_time,  # HITL -- forces run_async server-side too
        run_async=True,
    ))

    if result.job_id is not None:
        # Stops (and fires a callback) the moment the job reaches ANY
        # terminal poll state, including awaiting_approval -- see the
        # worker.py docstring referenced above. The platform's callback
        # handler branches on event.status == 'awaiting_approval' to know
        # there are pending_changes to show a human, vs. 'completed' meaning
        # the edit needed no approval at all.
        worker.start_background(result.job_id, recipe_input.callback_dispatcher, operation_id=result.operation_id)

    return EditAndAwaitReviewOutput(
        operation_id=result.operation_id, job_id=result.job_id,
        session_id=result.session_id, status=result.status.value,
    )


@dataclass
class ReviewDecision:
    change_id: str
    approved: bool
    feedback: str | None = None


@dataclass
class SubmitReviewAndResumeInput:
    session_id: str
    job_id: str
    decisions: list[ReviewDecision]  # item-level -- some True, some False, is the whole point
    callback_dispatcher: CallbackDispatcher
    default_approved: bool = True  # used only as the required top-level `approved` field


async def submit_review_and_resume(
    client: SuperDocsHTTPClient, worker: JobWorker, recipe_input: SubmitReviewAndResumeInput
) -> None:
    """
    The second half of Recipe 2, called once the platform has collected a
    human's per-item decisions (e.g. from an approval UI backed by the
    awaiting_approval callback's pending_changes). Demonstrates the
    batch-per-change approval shape: some changes approved, some rejected,
    in the same call.
    """
    await submit_for_approval(client, ApprovalInput(
        session_id=recipe_input.session_id,
        job_id=recipe_input.job_id,
        approved=recipe_input.default_approved,  # required top-level field, always sent
        changes=[
            ChangeDecision(change_id=d.change_id, approved=d.approved, feedback=d.feedback)
            for d in recipe_input.decisions
        ],
    ))

    # Resume polling to the next terminal state (expected: 'completed', now
    # that every pending change has an explicit decision).
    worker.start_background(recipe_input.job_id, recipe_input.callback_dispatcher)
