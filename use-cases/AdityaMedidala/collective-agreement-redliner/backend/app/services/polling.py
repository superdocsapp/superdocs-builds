"""
Shared bounded job-polling helper. Every SuperDocs async operation (upload
attachment, start a round, approve/deny decisions) returns a job_id and
needs the same pattern: poll get_job until some status condition is met,
capped so a stuck job can't loop forever. Third call site needed this
(negotiation_service, round_service.start_round, round_service.decide) —
factored out instead of copy-pasting it a third time.
"""

import logging
import time
from collections.abc import Callable

from app.superdocs_client import SuperDocsClient

logger = logging.getLogger(__name__)


def poll_job(
    client: SuperDocsClient,
    job_id: str,
    is_terminal: Callable[[dict], bool],
    max_attempts: int = 30,
    poll_interval: float = 1.0,
) -> dict:
    """Polls get_job(job_id) until is_terminal(job) is True, or gives up
    after max_attempts. Never loops unbounded."""
    job = client.get_job(job_id)
    attempts = 1
    while not is_terminal(job) and attempts < max_attempts:
        time.sleep(poll_interval)
        job = client.get_job(job_id)
        attempts += 1
    if not is_terminal(job):
        logger.warning(
            "job %s did not reach a terminal state after %d attempts (last status=%r)",
            job_id,
            max_attempts,
            job.get("status"),
        )
    return job
