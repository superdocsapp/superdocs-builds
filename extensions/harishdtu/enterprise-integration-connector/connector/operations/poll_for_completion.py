"""
poll_for_completion — a single GET /v1/jobs/{job_id} check. This is the
operation a recipe calls for an explicit "check status now" step; the
worker's poll_until_terminal (worker.py) is the loop this operation is one
iteration of, used internally by JobWorker.start_background for the
non-blocking long-running-job pattern.
"""
from __future__ import annotations

from connector.http_client import SuperDocsHTTPClient
from connector.worker import poll_once
from schemas.poll import PollInput, PollOutput


async def poll_for_completion(client: SuperDocsHTTPClient, input: PollInput) -> PollOutput:
    return await poll_once(client, input.job_id)
