# LangGraph quickstart

This quickstart compiles a real `StateGraph` with one deterministic
`edit_document` node. The node invokes the LangChain `StructuredTool` created by the
thin binding; upload, recovery, approval, and export remain in the shared core.

```bash
uv run --extra langgraph python -m quickstarts.langgraph.app
```

Choose this binding when document editing is one step in a durable graph with
branching, state, interrupts, or other LangGraph nodes.
