"""Orchestrator: routes a document request to the specialist
agents whose triggers match, runs them concurrently through the
reliability wrapper, and merges their results.

Routing here is trigger-keyword matching (v0, deterministic,
zero-latency, fully testable). Swap route() for an LLM intent
classifier later without touching agents or the reliability layer.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.agents.base import AgentResult, BaseAgent, DocumentContext
from app.reliability import ReliableAgentRunner


@dataclass
class OrchestratorResponse:
    context: DocumentContext
    results: list[AgentResult] = field(default_factory=list)

    @property
    def suggestion_count(self) -> int:
        return sum(len(r.suggestions) for r in self.results)


class Orchestrator:
    def __init__(self, agents: list[BaseAgent], runner: ReliableAgentRunner | None = None) -> None:
        self.agents = agents
        self.runner = runner or ReliableAgentRunner()

    def route(self, ctx: DocumentContext) -> list[BaseAgent]:
        matched = [a for a in self.agents if a.handles(ctx)]
        return matched or list(self.agents)  # nothing matched -> ask everyone, still useful for v0

    async def handle(self, ctx: DocumentContext) -> OrchestratorResponse:
        agents = self.route(ctx)
        results = await asyncio.gather(*(self.runner.run(agent, ctx) for agent in agents))
        return OrchestratorResponse(context=ctx, results=list(results))

    async def stream(self, ctx: DocumentContext):
        """Yield one status/result event per agent as it completes --
        this is what gives the UI a live, "agents at work" feel
        instead of one long silent wait."""
        agents = self.route(ctx)
        yield {"event": "routing", "agents": [a.name for a in agents]}
        tasks = {asyncio.create_task(self.runner.run(agent, ctx)): agent for agent in agents}
        for task in asyncio.as_completed(tasks):
            result = await task
            yield {"event": "agent_result", "result": result}
        yield {"event": "done"}
