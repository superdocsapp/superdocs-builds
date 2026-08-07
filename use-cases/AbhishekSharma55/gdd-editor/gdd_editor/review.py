"""Human-in-the-loop review: propose, show a diff, approve some, deny others.

This is the third call of the four-call minimum contract, and the one it is
easiest to skip. A design lead does not want an AI silently retuning numbers in
the mechanics document; they want to see two proposed changes and take one.

The flow:

    chat_async(approval_mode="ask_every_time")   ->  job pauses
    GET /v1/jobs/{id}                            ->  status awaiting_approval
    pending_changes(job)                         ->  the diff, per section
    POST /v1/chat/{session}/approve  {changes:[…]}  ->  per-change decisions
    GET /v1/jobs/{id}                            ->  completed

The property worth proving, and the one this asserts: **rejecting one change
does not discard the rest.** Verified live — a turn proposing two cooldown edits
had one approved and one denied, and the document came back with exactly the
approved edit applied and the denied one absent.

A note on the documented gotcha. Integrators are warned that proposed-change
content arrives as a JSON-encoded string needing a second parse. On this path,
on this account, it did **not** — `metadata.pending_changes` came back as a
real list. `superdocs_kit.changes.deep_parse` handles both shapes anyway, since
being wrong in the other direction costs an empty diff card and a confused
afternoon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from superdocs_kit import SuperDocs
from superdocs_kit.changes import Change
from superdocs_kit.docdiff import visible_text


@dataclass
class ReviewOutcome:
    proposed: list[Change]
    approved: list[str]
    denied: list[str]
    ops: int
    seconds: float
    final_html: str

    @property
    def summary(self) -> str:
        return (f"{len(self.proposed)} proposed, {len(self.approved)} approved, "
                f"{len(self.denied)} denied, {self.ops} operation(s)")


def propose(
    client: SuperDocs,
    *,
    session_id: str,
    document_html: str,
    instruction: str,
    label: str,
    log: Callable[[str], None] = print,
) -> tuple[str, list[Change]]:
    """Start a gated turn and return (job_id, proposed changes)."""
    job = client.chat_async(
        session_id=session_id,
        message=instruction,
        label=label,
        approval_mode="ask_every_time",
        document_html=document_html,
        model_tier="pro",
        thinking_depth="deep",
    )
    job_id = job["job_id"]
    # The operation is billed when the turn is submitted, not when it is
    # approved - so a denied change still costs. Worth knowing before you build
    # a review UI that proposes speculatively.
    paused = client.wait_for_job(
        job_id, stop_on=("awaiting_approval", "completed", "failed"), timeout=900
    )
    if paused.get("status") == "completed":
        log("  the model applied the change without pausing - nothing to review")
        return job_id, []
    changes = client.pending_changes(paused)
    log(f"  {len(changes)} change(s) proposed, awaiting a human")
    return job_id, changes


def render_diff(changes: list[Change]) -> str:
    """What a reviewer reads before deciding."""
    lines = []
    for i, c in enumerate(changes, 1):
        lines += [
            f"  [{i}] {c.operation} in section {str(c.chunk_id)[:8]}",
            f"      before: {visible_text(c.old_html or '')[:100]}",
            f"      after : {visible_text(c.new_html or '')[:100]}",
        ]
        if c.explanation:
            lines.append(f"      why   : {c.explanation[:100]}")
    return "\n".join(lines)


def decide(
    client: SuperDocs,
    *,
    session_id: str,
    job_id: str,
    changes: list[Change],
    accept: Callable[[Change], bool],
    feedback: str = "",
    ops: int = 0,
    log: Callable[[str], None] = print,
) -> ReviewOutcome:
    """Apply per-change decisions and wait for the job to finish."""
    started = time.monotonic()
    decisions = {c.change_id: bool(accept(c)) for c in changes}
    for c in changes:
        log(f"  {'APPROVE' if decisions[c.change_id] else 'DENY   '} "
            f"{c.change_id[:8]}  {visible_text(c.new_html or '')[:60]}")
    client.approve(session_id, job_id, decisions=decisions, feedback=feedback or None)
    final = client.wait_for_job(job_id, timeout=900)
    result = final.get("result") or {}
    html = (result.get("document_changes") or {}).get("updated_html") or ""
    if not html:
        html = client.export_text(session_id=session_id, fmt="html")
    return ReviewOutcome(
        proposed=changes,
        approved=[cid for cid, ok in decisions.items() if ok],
        denied=[cid for cid, ok in decisions.items() if not ok],
        ops=ops,  # charged when the turn was SUBMITTED; approving is free
        seconds=round(time.monotonic() - started, 1),
        final_html=html,
    )
