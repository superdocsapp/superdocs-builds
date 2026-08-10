# CrewAI quickstart

This quickstart runs a native CrewAI `Flow` whose start method invokes the generated
CrewAI tool. Telemetry and flow events are disabled for this local deterministic
comparison; no second model-provider key is needed.

```bash
uv run --extra crewai python -m quickstarts.crewai.app
```

Choose this binding when the same document capability belongs inside a CrewAI flow or
will be assigned to one or more CrewAI agents.
