# SuperDocs Framework Adapter

A framework-neutral adapter for integrating SuperDocs document operations
with agent frameworks such as LangChain, LangGraph, and LlamaIndex.

## Architecture

The project separates SuperDocs operations from agent-framework integrations.

```text
                         SuperDocs API
                              |
                              v
                     +------------------+
                     | SuperDocsClient  |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     | SuperDocsAdapter |
                     +--------+---------+
                              |
                              v
                     +------------------+
                     | ToolDefinition   |
                     +--------+---------+
                              |
              +---------------+---------------+
              |               |               |
              v               v               v
         LangChain        LangGraph       LlamaIndex
       StructuredTool        Node         FunctionTool
```

## Supported Operations

| Operation       | Tool name         | Current API support                |
| --------------- | ----------------- | ---------------------------------- |
| Edit document   | `edit_document`   | Supported through `/chat`          |
| Search document | `search_document` | Not currently exposed by SuperDocs |
| Export document | `export_document` | Not currently exposed by SuperDocs |

Unsupported operations return a structured `ToolResult.failure(...)`
rather than raising framework-specific exceptions.

## Installation

```bash
pip install -e .
```

Framework integrations are optional.

### LangChain

```bash
pip install langchain-core
```

### LangGraph

```bash
pip install langgraph
```

### LlamaIndex

```bash
pip install llama-index-core
```

## Testing

```bash
python3 -m pytest -v
```

The test suite validates:

* SuperDocs HTTP behavior
* authentication
* request payloads
* error handling
* framework-neutral tool definitions
* LangChain integration
* LangGraph integration
* LlamaIndex integration
* cross-framework tool compatibility

## Design Principles

### Framework independence

The core package does not import LangChain, LangGraph, or LlamaIndex.

### One implementation

SuperDocs API behavior exists only in `SuperDocsClient`.

Framework integrations adapt that client rather than duplicating it.

### Optional dependencies

Framework-specific packages are imported lazily and are not required
to use the core adapter.

### Stable tool contract

Every framework receives the same:

* `edit_document`
* `search_document`
* `export_document`

tool contract.

## Existing SuperDocs Integration

This adapter builds on the SuperDocs API behavior implemented in the
previous `live-doc-agent` extension.

The previous extension remains independent and untouched.
