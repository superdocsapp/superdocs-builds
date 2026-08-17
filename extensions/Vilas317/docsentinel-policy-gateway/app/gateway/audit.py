import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str
    request_id: str
    team: str
    tool: str
    allowed: bool
    status_code: int
    duration_ms: float
    cost: float
    previous_hash: str
    event_hash: str


@dataclass
class AuditLogger:
    events: list[AuditEvent] = field(default_factory=list)

    def record(self, *, request_id: str | None, team: str, tool: str,
               allowed: bool, status_code: int, duration_ms: float,
               cost: float = 0.0) -> AuditEvent:
        event_id = str(uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        previous_hash = self.events[-1].event_hash if self.events else ""
        payload = {
            "event_id": event_id,
            "timestamp": timestamp,
            "request_id": request_id or "",
            "team": team,
            "tool": tool,
            "allowed": allowed,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "cost": cost,
            "previous_hash": previous_hash,
        }
        event_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        event = AuditEvent(
            event_id=event_id,
            timestamp=timestamp,
            request_id=request_id or "",
            team=team,
            tool=tool,
            allowed=allowed,
            status_code=status_code,
            duration_ms=round(duration_ms, 2),
            cost=cost,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self.events.append(event)
        return event


DEFAULT_AUDIT_LOGGER = AuditLogger()
