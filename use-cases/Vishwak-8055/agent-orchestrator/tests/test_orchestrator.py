from app.agents.base import AgentResult, BaseAgent, DocumentContext
from app.orchestrator import Orchestrator


class AlwaysAgent(BaseAgent):
    name = "always"
    triggers = ("always",)

    async def run(self, ctx: DocumentContext) -> AgentResult:
        return AgentResult(agent_name=self.name, ok=True, summary="ran")


class NeverAgent(BaseAgent):
    name = "never"
    triggers = ("never-trigger-this",)

    async def run(self, ctx: DocumentContext) -> AgentResult:
        return AgentResult(agent_name=self.name, ok=True, summary="ran")


class FailingAgent(BaseAgent):
    name = "failing"
    triggers = ("fail",)

    async def run(self, ctx: DocumentContext) -> AgentResult:
        raise RuntimeError("boom")


async def test_route_matches_trigger():
    orch = Orchestrator(agents=[AlwaysAgent(), NeverAgent()])
    ctx = DocumentContext(selected_text="x", command="always do this")
    matched = orch.route(ctx)
    assert [a.name for a in matched] == ["always"]


async def test_route_falls_back_to_all_when_nothing_matches():
    orch = Orchestrator(agents=[AlwaysAgent(), NeverAgent()])
    ctx = DocumentContext(selected_text="x", command="totally unrelated command")
    matched = orch.route(ctx)
    assert len(matched) == 2


async def test_handle_merges_results():
    orch = Orchestrator(agents=[AlwaysAgent()])
    ctx = DocumentContext(selected_text="x", command="always")
    response = await orch.handle(ctx)
    assert len(response.results) == 1
    assert response.results[0].ok


async def test_handle_isolates_a_failing_agent():
    orch = Orchestrator(agents=[FailingAgent(), AlwaysAgent()])
    ctx = DocumentContext(selected_text="x", command="fail always")
    response = await orch.handle(ctx)
    names = {r.agent_name: r for r in response.results}
    assert names["failing"].ok is False
    assert names["always"].ok is True


async def test_stream_yields_routing_then_results_then_done():
    orch = Orchestrator(agents=[AlwaysAgent()])
    ctx = DocumentContext(selected_text="x", command="always")
    events = [e async for e in orch.stream(ctx)]
    assert events[0]["event"] == "routing"
    assert events[-1]["event"] == "done"
    assert any(e["event"] == "agent_result" for e in events)


async def test_suggestion_count_sums_across_agents():
    orch = Orchestrator(agents=[AlwaysAgent()])
    ctx = DocumentContext(selected_text="x", command="always")
    response = await orch.handle(ctx)
    assert response.suggestion_count == 0
