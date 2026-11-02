#!/usr/bin/env python3
"""
End-to-end test of the superdocs-framework-adapter.

This script exercises the full stack:
  1. SuperDocsClient — upload, edit, search, export
  2. LangChain integration — tool invocation
  3. LangGraph integration — node execution
  4. LlamaIndex integration — tool call

Requires:
  SUPERDOCS_API_KEY  (read from .env)
  SUPERDOCS_BASE_URL (read from .env)
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Load credentials from .env
# ---------------------------------------------------------------------------

env_path = Path(__file__).parent.parent / "live-doc-agent" / ".env"
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

API_KEY = os.environ["SUPERDOCS_API_KEY"]
BASE_URL = os.environ["SUPERDOCS_BASE_URL"]

DOCUMENT_CONTENT = """
# SuperDocs Framework Adapter

## Introduction

The framework-neutral SuperDocs adapter lets you expose SuperDocs document
editing capabilities to any LLM agent framework.

## Features

- Unified tool interface (edit, search, export)
- LangChain support
- LangGraph support
- LlamaIndex support
- No hard dependency on any framework in the core package
""".strip()


def ok(label: str) -> None:
    print(f"  \033[32m✓\033[0m {label}")


def fail(label: str, detail: str) -> None:
    print(f"  \033[31m✗\033[0m {label}")
    print(f"    {detail}")
    sys.exit(1)


def section(title: str) -> None:
    print(f"\n\033[1m{'─' * 60}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'─' * 60}\033[0m")


# ---------------------------------------------------------------------------
# Step 1 — core client
# ---------------------------------------------------------------------------

section("Step 1: Core SuperDocsClient")

import superdocs_adapter  # noqa: E402

from superdocs_adapter import (  # noqa: E402
    SuperDocsClient,
    ToolName,
    create_tool_definitions,
)

client = SuperDocsClient(base_url=BASE_URL, api_key=API_KEY)
ok(f"SuperDocsClient created (base_url={BASE_URL})")

# upload
document_id = client.upload("Adapter E2E Test", DOCUMENT_CONTENT)
ok(f"upload() returned document_id={document_id!r}")

# search
result = client.search_document(document_id, "LangChain")
if not result.success:
    fail("search_document", result.error)
matches = result.data["count"]
ok(f"search_document('LangChain') — {matches} match(es)")

# export
result = client.export_document(document_id, "markdown")
if not result.success:
    fail("export_document", result.error)
ok(f"export_document('markdown') — {len(result.data['content'])} chars")

# edit
result = client.edit_document(
    document_id,
    "Add a short sentence to the Introduction section describing that the "
    "adapter is zero-dependency at its core.",
)
if not result.success:
    fail("edit_document", result.error)
changes = result.data.get("changes", [])
ok(f"edit_document() — {len(changes)} change(s) returned by SuperDocs API")

# ---------------------------------------------------------------------------
# Step 2 — LangChain integration
# ---------------------------------------------------------------------------

section("Step 2: LangChain integration")

from superdocs_adapter.integrations.langchain import create_langchain_tools  # noqa: E402

definitions = create_tool_definitions(client)
lc_tools = create_langchain_tools(definitions)
ok(f"create_langchain_tools() — {len(lc_tools)} tool(s): {[t.name for t in lc_tools]}")

edit_lc = next(t for t in lc_tools if t.name == "edit_document")
lc_result = edit_lc.invoke(
    {
        "document_id": document_id,
        "instruction": "Fix any typos in the Features section.",
    }
)
if not lc_result.success:
    fail("LangChain edit_document invoke", lc_result.error)
ok(f"LangChain invoke — {len(lc_result.data.get('changes', []))} change(s)")

# ---------------------------------------------------------------------------
# Step 3 — LangGraph integration
# ---------------------------------------------------------------------------

section("Step 3: LangGraph integration")

from superdocs_adapter.integrations.langgraph import (  # noqa: E402
    create_langgraph_nodes,
    execute_langgraph_node,
)

nodes = create_langgraph_nodes(definitions)
ok(f"create_langgraph_nodes() — nodes: {list(nodes.keys())}")

state = {"document_id": document_id, "query": "LlamaIndex"}
lg_result = execute_langgraph_node(nodes["search_document"], state)
if not lg_result.success:
    fail("LangGraph execute_langgraph_node", lg_result.error)
ok(f"LangGraph node 'search_document' — count={lg_result.data.get('count', 0)}")

# ---------------------------------------------------------------------------
# Step 4 — LlamaIndex integration
# ---------------------------------------------------------------------------

section("Step 4: LlamaIndex integration")

from superdocs_adapter.integrations.llamaindex import create_llamaindex_tools  # noqa: E402

li_tools = create_llamaindex_tools(definitions)
ok(f"create_llamaindex_tools() — {len(li_tools)} tool(s): {[t.metadata.name for t in li_tools]}")

export_li = next(t for t in li_tools if t.metadata.name == "export_document")
li_output = export_li.call(document_id=document_id, format="markdown")
if not li_output.raw_output.success:
    fail("LlamaIndex export_document call", li_output.raw_output.error)
ok(f"LlamaIndex call — {len(li_output.raw_output.data.get('content', ''))} chars")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

section("E2E Result")
print(f"\n  \033[1;32m✓ All steps passed.\033[0m\n")
