"""Errors raised by the SuperDocs client.

The split that matters here is retryable versus not. A 503 is worth waiting on; a 401 will be a 401
forever and retrying it just wastes the user's time and hides the real problem.
"""

from __future__ import annotations


class SuperDocsError(Exception):
    """Base class. Carries the status code and body when there was an HTTP response."""

    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.message} (HTTP {self.status_code})"


class SuperDocsAuthError(SuperDocsError):
    """401/403. The key is missing, wrong, or lacks permission. Never retried."""


class SuperDocsBadRequest(SuperDocsError):
    """4xx that is our fault. Never retried - the same request will fail the same way."""


class SuperDocsRateLimited(SuperDocsError):
    """429. Retryable, and honours Retry-After when the server sends one."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class SuperDocsUnavailable(SuperDocsError):
    """5xx, connection failure or timeout. Retryable."""

    retryable = True


class SuperDocsSessionBusy(SuperDocsError):
    """409 `session_busy`: the session already has an active job.

    Retryable, which makes it the exception to "4xx is never retried". A session holds one active
    job at a time, and a job parked at `awaiting_approval` keeps holding it for as long as the
    human takes to review. So this is a transient conflict wearing a client-error status code.

    docs-lint mostly avoids it by giving each document its own session, but a resumed run can still
    meet it, and backing off is the right response.
    """

    retryable = True

    def __init__(self, message: str, *, active_jobs: int | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.active_jobs = active_jobs


class SuperDocsJobFailed(SuperDocsError):
    """A job reached a terminal `failed` state. Not a transport problem, so not retryable.

    Carries the job id so the caller can report which document died and why.
    """

    def __init__(self, message: str, *, job_id: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.job_id = job_id


class SuperDocsJobTimeout(SuperDocsError):
    """A job did not reach a terminal state within the caller's deadline.

    Distinct from `SuperDocsUnavailable`: the service is fine and the job may still be running.
    Large documents and deep model settings can take minutes with no visible progress. The run
    records the job id so the work can be resumed rather than paid for twice.
    """

    def __init__(self, message: str, *, job_id: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.job_id = job_id
