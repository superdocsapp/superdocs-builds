from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.policy import Policy

# Only these bill. Upload, parse, export and every read are free, so counting
# them would produce a number that does not match the SuperDocs invoice.
BILLABLE_TOOLS = frozenset({"chat", "chat_async"})


@dataclass
class TeamQuota:
    monthly_limit: int
    used: int = 0
    reserved: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def available(self) -> int:
        return max(0, self.monthly_limit - self.used - self.reserved)

    def reserve(self, n: int = 1) -> bool:
        with self._lock:
            if self.available >= n:
                self.reserved += n
                return True
            return False

    def settle(self, n: int = 1) -> None:
        with self._lock:
            self.reserved = max(0, self.reserved - n)
            self.used += n

    def release(self, n: int = 1) -> None:
        with self._lock:
            self.reserved = max(0, self.reserved - n)


class QuotaStore:
    def __init__(self) -> None:
        self._teams: dict[str, TeamQuota] = {}

    @classmethod
    def from_policy(cls, policy: Policy) -> QuotaStore:
        """Register every team that declares a limit.

        A team with no `quota:` block is deliberately absent rather than
        registered with an infinite limit — `get()` returning None is what the
        proxy reads as "unmetered".
        """
        store = cls()
        for team in policy.teams:
            if team.monthly_edits is not None:
                store.register(team.name, team.monthly_edits)
        return store

    def register(self, team_name: str, monthly_limit: int) -> None:
        self._teams[team_name] = TeamQuota(monthly_limit=monthly_limit)

    def get(self, team_name: str) -> TeamQuota | None:
        return self._teams.get(team_name)

    def is_billable(self, tool_name: str) -> bool:
        return tool_name in BILLABLE_TOOLS
