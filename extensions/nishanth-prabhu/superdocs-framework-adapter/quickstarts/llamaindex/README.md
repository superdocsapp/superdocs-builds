# SuperDocs + LlamaIndex

This example shows how to expose the framework-neutral SuperDocs adapter
as LlamaIndex tools.

## Install

```bash
pip install -e ../..
pip install llama-index-core
```

## Example

```python
from superdocs_adapter import (
    SuperDocsClient,
    create_tool_definitions,
)

from superdocs_adapter.integrations.llamaindex import (
    create_llamaindex_tools,
)


client = SuperDocsClient(
    base_url="https://api.superdocs.app/v1",
    api_key="YOUR_SUPERDOCS_API_KEY",
)

definitions = create_tool_definitions(client)

tools = create_llamaindex_tools(definitions)

for tool in tools:
    print(tool.metadata.name)
```

Expected output:

```text
edit_document
search_document
export_document
```

## Architecture

```text
SuperDocsClient
       |
       v
ToolDefinition
       |
       v
LlamaIndex FunctionTool
```

The core adapter remains independent from LlamaIndex.
