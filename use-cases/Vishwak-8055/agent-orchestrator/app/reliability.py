"""Reliability wrapper: retries with backoff and a simple circuit
breaker per agent. This is what actually produces a "never hard
fails" feel -- not zero bugs (nothing gets that), but every failure
has a graceful path and the rest of the request continues.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.agents.base import AgentResult, DocumentContext


@dataclass
class CircuitState:
    failures: int = 0
    opened_at: float | None = None
    threshold: int = 3
    cooldown_seconds: float = 30.0

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at > self.cooldown_seconds:
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class ReliableAgentRunner:
    def __init__(self, max_retries: int = 2, base_delay: float = 0.05) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._circuits: dict[str, CircuitState] = {}

    def _circuit_for(self, agent_name: str) -> CircuitState:
        return self._circuits.setdefault(agent_name, CircuitState())

    async def run(self, agent, ctx: DocumentContext) -> AgentResult:
        circuit = self._circuit_for(agent.name)
        if circuit.is_open():
            return AgentResult(
                agent_name=agent.name,
                ok=False,
                error="circuit_open",
                summary=f"{agent.name} temporarily skipped after repeated failures.",
            )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                result = await agent.run(ctx)
                circuit.record_success()
                return result
            except Exception as exc:  # noqa: BLE001 -- deliberately broad, isolating agent failures
                last_error = exc
                circuit.record_failure()
                if attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay * (2**attempt))

        return AgentResult(
            agent_name=agent.name,
            ok=False,
            error=str(last_error),
            summary=f"{agent.name} failed after {self.max_retries + 1} attempt(s); request continued without it.",
        )
