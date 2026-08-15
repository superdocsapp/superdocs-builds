"""
submit_for_approval — wraps POST /v1/chat/{session_id}/approve.

The single most important line in this file is that `approved` is ALWAYS sent
at the top level of the outgoing body, in every shape, because
ApprovalInput.approved is a required (non-optional, no-default) field — it is
structurally impossible to construct a valid ApprovalInput without it, which
is exactly how this connector avoids the "missing top-level approved -> 422"
trap the SuperDocs docs call out as the most common integration mistake.
"""
from __future__ import annotations

from connector.http_client import SuperDocsHTTPClient
from schemas.approval import ApprovalInput, ApprovalOutput


def _build_request_body(input: ApprovalInput) -> dict:
    body: dict = {
        "job_id": input.job_id,
        "approved": input.approved,  # ALWAYS present at the top level.
    }
    if input.change_id is not None:
        body["change_id"] = input.change_id
        if input.feedback is not None:
            body["feedback"] = input.feedback
    elif input.change_ids is not None:
        body["changes"] = [{"change_id": cid} for cid in input.change_ids]
    elif input.changes is not None:
        body["changes"] = [
            {k: v for k, v in {
                "change_id": c.change_id, "approved": c.approved, "feedback": c.feedback,
            }.items() if v is not None}
            for c in input.changes
        ]
    return body


async def submit_for_approval(client: SuperDocsHTTPClient, input: ApprovalInput) -> ApprovalOutput:
    body = _build_request_body(input)
    payload = await client.post_json(f"/v1/chat/{input.session_id}/approve", body)

    applied: list[str] = []
    rejected: list[str] = []
    if input.change_id is not None:
        (applied if input.approved else rejected).append(input.change_id)
    elif input.change_ids is not None:
        (applied if input.approved else rejected).extend(input.change_ids)
    elif input.changes is not None:
        for c in input.changes:
            decision = c.approved if c.approved is not None else input.approved
            (applied if decision else rejected).append(c.change_id)

    return ApprovalOutput(
        job_id=input.job_id,
        status=payload.get("status", "in_progress"),
        applied=applied,
        rejected=rejected,
    )
