import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.gateway.policy import DEFAULT_GATEWAY_POLICY


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
    storage_path: Path | None = None

    def __post_init__(self) -> None:
        if self.storage_path is None:
            configured_path = DEFAULT_GATEWAY_POLICY.audit_persistence.path
            self.storage_path = Path(configured_path)

        if DEFAULT_GATEWAY_POLICY.audit_persistence.enabled:
            self._load_events()

    def _load_events(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return

        with self.storage_path.open("r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    data = json.loads(line)
                    event = AuditEvent(**data)
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Invalid audit event at line {line_number}."
                    ) from exc

                self._validate_event(event)
                self.events.append(event)

    @staticmethod
    def _event_payload(event: AuditEvent) -> dict:
        return {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "request_id": event.request_id,
            "team": event.team,
            "tool": event.tool,
            "allowed": event.allowed,
            "status_code": event.status_code,
            "duration_ms": event.duration_ms,
            "cost": event.cost,
            "previous_hash": event.previous_hash,
        }

    @classmethod
    def _calculate_hash(cls, event: AuditEvent) -> str:
        payload = cls._event_payload(event)

        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def _validate_event(self, event: AuditEvent) -> None:
        expected_previous_hash = (
            self.events[-1].event_hash
            if self.events
            else ""
        )

        if event.previous_hash != expected_previous_hash:
            raise ValueError(
                "Audit hash chain is invalid: "
                f"event {event.event_id} has an unexpected "
                "previous_hash."
            )

        expected_hash = self._calculate_hash(event)

        if event.event_hash != expected_hash:
            raise ValueError(
                "Audit hash chain is invalid: "
                f"event {event.event_id} has an invalid event_hash."
            )

    def _persist(self, event: AuditEvent) -> None:
        if (
            not DEFAULT_GATEWAY_POLICY.audit_persistence.enabled
            or self.storage_path is None
        ):
            return

        self.storage_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self.storage_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            json.dump(
                self._event_payload(event)
                | {"event_hash": event.event_hash},
                file,
                sort_keys=True,
            )
            file.write("\n")

    def record(
        self,
        *,
        request_id: str | None,
        team: str,
        tool: str,
        allowed: bool,
        status_code: int,
        duration_ms: float,
        cost: float | None = None,
    ) -> AuditEvent:
        event_id = str(uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        previous_hash = (
            self.events[-1].event_hash
            if self.events
            else ""
        )

        if cost is None:
            cost = (
                DEFAULT_GATEWAY_POLICY.audit_cost_policy
                .get_cost(tool)
            )

        cost = round(float(cost), 6)
        duration_ms = round(float(duration_ms), 2)

        payload = {
            "event_id": event_id,
            "timestamp": timestamp,
            "request_id": request_id or "",
            "team": team,
            "tool": tool,
            "allowed": allowed,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "cost": cost,
            "previous_hash": previous_hash,
        }

        event_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        event = AuditEvent(
            event_id=event_id,
            timestamp=timestamp,
            request_id=request_id or "",
            team=team,
            tool=tool,
            allowed=allowed,
            status_code=status_code,
            duration_ms=duration_ms,
            cost=cost,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

        self.events.append(event)
        self._persist(event)

        return event


DEFAULT_AUDIT_LOGGER = AuditLogger()
