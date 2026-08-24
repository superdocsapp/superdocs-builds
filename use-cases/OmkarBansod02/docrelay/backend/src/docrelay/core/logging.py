import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
_OAUTH_CALLBACK_PATH = "/api/v1/google/oauth/callback"


class OAuthCallbackAccessLogFilter(logging.Filter):
    """Keep one-time OAuth codes and state values out of Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 3:
            return True
        path = record.args[2]
        if isinstance(path, str) and path.startswith(f"{_OAUTH_CALLBACK_PATH}?"):
            values = list(record.args)
            values[2] = f"{_OAUTH_CALLBACK_PATH}?[REDACTED]"
            record.args = tuple(values)
        return True


class JsonFormatter(logging.Formatter):
    """Small structured formatter that never serializes request bodies or secrets."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id:
            event["request_id"] = request_id
        safe_metadata = getattr(record, "safe_metadata", None)
        if isinstance(safe_metadata, dict):
            event.update(safe_metadata)
        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)
        return json.dumps(event, separators=(",", ":"), ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, OAuthCallbackAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(OAuthCallbackAccessLogFilter())


def bind_request_id(request_id: str) -> Token[str | None]:
    return request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_context.reset(token)
