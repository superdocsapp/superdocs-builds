# SuperDocs + LangChain

This example shows how to expose the framework-neutral SuperDocs adapter
as LangChain tools.

## Install

```bash
pip install -e ../..
pip install langchain-core
```

## Example

```python
from superdocs_adapter import (
    SuperDocsClient,
    create_tool_definitions,
)

from superdocs_adapter.integrations.langchain import (
    create_langchain_tools,
)


client = SuperDocsClient(
    base_url="https://api.superdocs.app/v1",
    api_key="YOUR_SUPERDOCS_API_KEY",
)

definitions = create_tool_definitions(client)

tools = create_langchain_tools(definitions)

for tool in tools:
    print(tool.name)
```

Expected output:

```text
edit_document
search_document
export_document
```

## Architecture

The LangChain integration does not implement SuperDocs operations itself.

```text
SuperDocsClient
       |
       v
ToolDefinition
       |
       v
LangChain StructuredTool
```

This keeps the SuperDocs client independent from LangChain.
