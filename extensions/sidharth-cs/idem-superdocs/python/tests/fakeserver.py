"""A fake SuperDocs that counts how many times an edit was actually applied.

`applies` is the number the whole harness is built to assert on: for one
operation key it must be 1, whatever the network did.

The count is an append-only log rather than a JSON document that gets read,
incremented and rewritten. Two reasons, and the second is the important one:

  * it survives the process that made it, which the restart scenario needs
  * appending is atomic, so concurrent callers cannot lose an increment

A read-modify-write counter would be the one bug this harness must not have.
It could under-count applies under exactly the concurrency the harness exists
to test, and an under-count is a double-apply that goes unreported.
"""

from __future__ import annotations

import json
from pathlib import Path


class LostResponse(Exception):
    """The edit was applied and the answer never came back. This is the shape
    that produced eight duplicate paragraphs in a real document."""

    sent = True  # the request left the client; the library must fail closed


class Conflict(Exception):
    status = 409
    sent = True


class FakeServer:
    def __init__(self, path: str | Path) -> None:
        self.log = Path(path)
        self.log.touch()

    # ---- state --------------------------------------------------------------

    def _entries(self) -> list[dict]:
        text = self.log.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    @property
    def applies(self) -> int:
        """How many edits this server actually performed."""
        return len([e for e in self._entries() if e["kind"] == "edit"])

    @property
    def approvals(self) -> int:
        """How many approvals this server actually recorded. The Review-surface
        equivalent of `applies`: approving twice is as wrong as editing twice."""
        return len([e for e in self._entries() if e["kind"] == "approve"])

    def applies_for(self, operation_key: str) -> int:
        """How many times one specific key was applied. The per-key form of the
        assertion the whole harness is built around."""
        return len([e for e in self._entries()
                    if e["kind"] == "edit" and e["operation_key"] == operation_key])

    def job(self, job_id: str) -> dict | None:
        return next((e for e in self._entries() if e["job_id"] == job_id), None)

    def job_status(self, job_id: str) -> str:
        """The Review job lifecycle as the server sees it. A job that was
        approved but whose approval never settled stays `awaiting_approval` —
        which is bug 5 exactly: the approve call returned success and the job
        never moved."""
        approvals = [e for e in self._entries()
                     if e["kind"] == "approve" and e["job_id"] == job_id]
        if any(a["settled"] for a in approvals):
            return "completed"
        return "awaiting_approval"

    def approve(self, operation_key: str, job_id: str, *,
                lose_response: bool = False, settles: bool = True) -> dict:
        """Decide a proposed change. Recording the approval IS the apply — it is
        the billable, state-changing half of the Review flow.

        `settles=False` reproduces the wedge from the evidence: the approve call
        succeeds, and the job never reaches a terminal state.
        """
        entry = {"kind": "approve", "job_id": job_id, "operation_key": operation_key,
                 "settled": settles, "status": "completed" if settles else "awaiting_approval"}
        with self.log.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")

        if lose_response:
            raise LostResponse(f"approval of {job_id} recorded, response never arrived")
        return {"job_id": job_id, "batch_complete": settles}

    def find_by_operation_key(self, operation_key: str) -> dict | None:
        """A server that honoured idempotency keys could answer this. This one
        records the key so the harness can show what becomes possible when it
        does — see SPEC.md section 6."""
        return next((e for e in self._entries() if e["operation_key"] == operation_key), None)

    # ---- the operation ------------------------------------------------------

    def chat_async(self, operation_key: str, *, lose_response: bool = False,
                   conflict: bool = False) -> dict:
        """Apply an edit, then optionally lose the answer on the way back.

        The apply is recorded *before* the response is lost, which is what makes
        the partition scenario a real test: the server did the work, and the
        client has no way to know.
        """
        if conflict:
            raise Conflict("session state rejects this call")

        job = {"kind": "edit", "job_id": f"job-{operation_key}-{self.applies + 1}",
               "status": "completed", "operation_key": operation_key}
        # O_APPEND: one atomic write per apply, so nothing can be lost.
        with self.log.open("a") as handle:
            handle.write(json.dumps(job) + "\n")

        if lose_response:
            raise LostResponse(f"applied as {job['job_id']}, response never arrived")
        return job
