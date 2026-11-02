# SuperDocs + LangGraph

This example shows how to expose the framework-neutral SuperDocs adapter
as LangGraph-compatible nodes.

## Install

```bash
pip install -e ../..
pip install langgraph
```

## Example

```python
from superdocs_adapter import (
    SuperDocsClient,
    create_tool_definitions,
)

from superdocs_adapter.integrations.langgraph import (
    create_langgraph_nodes,
)


client = SuperDocsClient(
    base_url="https://api.superdocs.app/v1",
    api_key="YOUR_SUPERDOCS_API_KEY",
)

definitions = create_tool_definitions(client)

nodes = create_langgraph_nodes(definitions)

edit_node = nodes["edit_document"]

state = {
    "document_id": "document-123",
    "instruction": "Update the introduction.",
}

result_state = edit_node(state)

print(result_state["superdocs_result"])
```

## Architecture

```text
SuperDocsClient
       |
       v
ToolDefinition
       |
       v
LangGraph Node
       |
       v
SuperDocs ToolResult
```

The LangGraph integration only adapts the interface.
It does not contain SuperDocs-specific HTTP logic.
