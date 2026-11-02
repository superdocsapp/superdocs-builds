class SuperDocsError(Exception):
    """Base for every SuperDocs client failure."""


class NotConfigured(SuperDocsError):
    """SUPERDOCS_API_KEY missing — put it in .env (see .env.example)."""


class AuthenticationFailed(SuperDocsError):
    """401/403 — the key is wrong or revoked; make a new one in the app."""


class ResourceNotFound(SuperDocsError):
    """404 — the session, job, or document id does not exist on the server."""


class RequestFailed(SuperDocsError):
    """Other 4xx — the request body was refused; the server's reason is attached."""


class MalformedResponse(SuperDocsError):
    """2xx but the body is not the JSON shape the API documents."""


class TransportError(SuperDocsError):
    """Timeout or network failure — retry later or check connectivity."""


class BudgetExceeded(SuperDocsError):
    """The run hit MAX_OPS_PER_RUN — raise the cap in .env only if you mean to spend more."""
