from app.agents.base import AgentResult, BaseAgent, DocumentContext
from app.reliability import ReliableAgentRunner


class FlakyAgent(BaseAgent):
    name = "flaky"

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def run(self, ctx: DocumentContext) -> AgentResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return AgentResult(agent_name=self.name, ok=True, summary="recovered")


class AlwaysFailsAgent(BaseAgent):
    name = "always_fails"

    async def run(self, ctx: DocumentContext) -> AgentResult:
        raise RuntimeError("permanent")


async def test_retries_then_succeeds():
    runner = ReliableAgentRunner(max_retries=2, base_delay=0.001)
    agent = FlakyAgent(fail_times=2)
    ctx = DocumentContext(selected_text="x", command="x")
    result = await runner.run(agent, ctx)
    assert result.ok
    assert agent.calls == 3


async def test_gives_up_after_max_retries():
    runner = ReliableAgentRunner(max_retries=1, base_delay=0.001)
    agent = AlwaysFailsAgent()
    ctx = DocumentContext(selected_text="x", command="x")
    result = await runner.run(agent, ctx)
    assert result.ok is False
    assert result.error == "permanent"


async def test_circuit_opens_after_threshold():
    runner = ReliableAgentRunner(max_retries=0, base_delay=0.001)
    agent = AlwaysFailsAgent()
    ctx = DocumentContext(selected_text="x", command="x")
    circuit = runner._circuit_for(agent.name)
    circuit.threshold = 2
    await runner.run(agent, ctx)
    await runner.run(agent, ctx)
    result = await runner.run(agent, ctx)
    assert result.error == "circuit_open"


async def test_circuit_recovers_after_cooldown():
    runner = ReliableAgentRunner(max_retries=0, base_delay=0.001)
    agent = FlakyAgent(fail_times=1)
    ctx = DocumentContext(selected_text="x", command="x")
    circuit = runner._circuit_for(agent.name)
    circuit.threshold = 1
    circuit.cooldown_seconds = 0
    await runner.run(agent, ctx)
    result = await runner.run(agent, ctx)
    assert result.ok
