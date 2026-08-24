from enum import StrEnum
from typing import Any


class GoogleErrorCode(StrEnum):
    OAUTH_NOT_CONFIGURED = "GOOGLE_OAUTH_NOT_CONFIGURED"
    INVALID_OAUTH_STATE = "GOOGLE_INVALID_OAUTH_STATE"
    OAUTH_ACCESS_DENIED = "GOOGLE_OAUTH_ACCESS_DENIED"
    REAUTH_REQUIRED = "GOOGLE_REAUTH_REQUIRED"
    WATCH_AUTHORIZATION_REQUIRED = "GOOGLE_WATCH_AUTHORIZATION_REQUIRED"
    PERMISSION_DENIED = "GOOGLE_PERMISSION_DENIED"
    CONNECTION_NOT_FOUND = "GOOGLE_CONNECTION_NOT_FOUND"
    FILE_NOT_FOUND = "GOOGLE_FILE_NOT_FOUND"
    UNSUPPORTED_SOURCE_TYPE = "UNSUPPORTED_SOURCE_TYPE"
    SOURCE_TRASHED = "SOURCE_TRASHED"
    SOURCE_CHANGED_DURING_CAPTURE = "SOURCE_CHANGED_DURING_CAPTURE"
    UNSUPPORTED_BACKUP_LOCATION = "GOOGLE_UNSUPPORTED_BACKUP_LOCATION"
    RATE_LIMITED = "GOOGLE_RATE_LIMITED"
    UNAVAILABLE = "GOOGLE_UNAVAILABLE"
    INVALID_RESPONSE = "GOOGLE_INVALID_RESPONSE"


class GoogleIntegrationError(RuntimeError):
    def __init__(
        self,
        code: GoogleErrorCode,
        message: str,
        *,
        retryable: bool = False,
        safe_details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.safe_details = safe_details or {}
        super().__init__(message)


class GoogleOAuthProviderError(GoogleIntegrationError):
    def __init__(self, oauth_error: str, *, during_refresh: bool = False) -> None:
        if oauth_error == "invalid_grant" and during_refresh:
            super().__init__(
                GoogleErrorCode.REAUTH_REQUIRED,
                "Google authorization is no longer valid; reconnect the account",
            )
            return
        if oauth_error == "invalid_grant":
            super().__init__(
                GoogleErrorCode.INVALID_OAUTH_STATE,
                "The Google authorization code is expired or invalid; restart authorization",
            )
            return
        if oauth_error in {"access_denied", "admin_policy_enforced", "org_internal"}:
            super().__init__(
                GoogleErrorCode.OAUTH_ACCESS_DENIED,
                "Google authorization was denied or blocked by account policy",
            )
            return
        super().__init__(
            GoogleErrorCode.UNAVAILABLE,
            "Google OAuth could not complete the request",
            retryable=oauth_error in {"temporarily_unavailable", "server_error"},
        )
