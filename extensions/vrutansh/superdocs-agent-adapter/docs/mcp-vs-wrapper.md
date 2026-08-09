# Hosted MCP server or adapter?

SuperDocs exposes the same platform through REST and its hosted MCP server. The right
choice depends on where workflow policy should live.

## Use the hosted MCP server directly when

- The agent host already supports Streamable HTTP MCP reliably.
- You want SuperDocs tools discovered dynamically.
- The agent should choose and sequence a broad set of SuperDocs operations.
- Minimal integration code matters more than a stable application-specific interface.
- You do not need the same abstraction across non-MCP frameworks.

This is normally the fastest route for Cursor, Claude Desktop, and other native MCP
clients.

## Use this wrapper when

- A framework does not implement MCP, or implements it differently.
- Multiple frameworks must share exactly the same behavior.
- The application should expose one constrained workflow instead of every tool.
- You need application-owned timeouts, retries, logging, approval policy, and tests.
- Tool schemas and outputs must remain versioned even if a framework changes.
- You want contract tests without connecting to a live hosted tool server.

## Use both when

An application can use this adapter for its guarded production workflow while giving
trusted developer agents direct MCP access for exploration. Both reach the same
SuperDocs documents; the difference is control and integration shape, not capability.
