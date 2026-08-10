# OpenAI Agents SDK quickstart

This quickstart creates a real OpenAI `Agent` with the generated `FunctionTool`
attached. It invokes that native tool directly for the parity run, avoiding an
additional model call and `OPENAI_API_KEY` requirement.

```bash
uv run --extra openai-agents python -m quickstarts.openai_agents.app
```

In an application that already uses the Agents SDK, pass the returned agent to
`Runner.run` or `Runner.run_sync`. The SDK then owns the model/tool loop; the shared
adapter still owns SuperDocs recovery, review, and export.

See the [official OpenAI Agents SDK quickstart](https://developers.openai.com/api/docs/guides/agents/quickstart).
