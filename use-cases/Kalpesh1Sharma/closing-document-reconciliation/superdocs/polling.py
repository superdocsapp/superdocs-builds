from __future__ import annotations

import time
from typing import Any

from superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
}


def wait_until_action_needed(
    *,
    client: SuperDocsClient,
    job_id: str,
    timeout_seconds: int = 180,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """
    Poll until the job:
    - needs human input,
    - completes,
    - fails,
    - or times out.
    """

    started = time.monotonic()
    last_status = None

    while True:
        job = client.get_job(
            job_id=job_id
        )

        status = job.get(
            "status"
        )

        if status != last_status:
            print(
                f"  Job status: {status}"
            )
            last_status = status

        if status == "awaiting_approval":
            return job

        if status == "completed":
            return job

        if status == "failed":
            raise SuperDocsError(
                job.get(
                    "error",
                    "SuperDocs job failed.",
                )
            )

        if status == "cancelled":
            raise SuperDocsError(
                "SuperDocs job was cancelled."
            )

        elapsed = (
            time.monotonic()
            - started
        )

        if elapsed >= timeout_seconds:
            raise TimeoutError(
                (
                    f"Job {job_id} did not reach an "
                    f"actionable state within "
                    f"{timeout_seconds} seconds."
                )
            )

        if elapsed >= 30:
            print(
                f"  Still processing... "
                f"{int(elapsed)}s elapsed"
            )

        time.sleep(
            poll_interval
        )