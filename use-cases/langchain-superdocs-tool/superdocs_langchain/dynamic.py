"""
Dynamic Tool Binding module for SuperDocs.
Generates typed LangChain tools dynamically at runtime from live SuperDocs REST/OpenAPI or MCP schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Type

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.models import ToolResponse

logger = logging.getLogger(__name__)

# JSON Schema type to Python type mapping
_JSON_TYPE_MAP: Dict[str, Type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_to_pydantic_fields(properties: Dict[str, Any], required_fields: List[str]) -> Dict[str, Any]:
    """Convert JSON schema properties dictionary into dynamic Pydantic field definitions."""
    fields: Dict[str, Any] = {}
    for name, prop in properties.items():
        prop_type_str = prop.get("type", "string")
        py_type = _JSON_TYPE_MAP.get(prop_type_str, Any)
        description = prop.get("description", "")
        default_val = prop.get("default", ... if name in required_fields else None)

        if name in required_fields and default_val is ...:
            fields[name] = (py_type, Field(..., description=description))
        else:
            fields[name] = (Optional[py_type], Field(default=default_val, description=description))

    return fields


def build_dynamic_tool(
    declaration: Dict[str, Any],
    client: SuperDocsClient,
) -> BaseTool:
    """
    Construct a LangChain StructuredTool dynamically from a single tool schema declaration.
    Supports both MCP tool specification and standard OpenAI/JSONSchema tool formats.
    """
    tool_name = declaration.get("name") or declaration.get("id") or "unnamed_tool"
    description = declaration.get("description", f"Dynamic tool: {tool_name}")
    params = declaration.get("parameters") or declaration.get("inputSchema") or {}

    properties = params.get("properties", {})
    required = params.get("required", [])

    # Dynamically build Pydantic model for argument validation
    model_name = f"{''.join(word.capitalize() for word in tool_name.split('_'))}ArgsSchema"
    fields = _json_schema_to_pydantic_fields(properties, required)
    dynamic_args_schema = create_model(model_name, **fields)

    def tool_func(**kwargs: Any) -> str:
        """Dynamic tool execution closure."""
        # Filter out None values that have defaults or are optional
        cleaned_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        response: ToolResponse = client.execute_dynamic_tool(tool_name, cleaned_kwargs)
        return json.dumps(response.model_dump(), indent=2)

    async def tool_afunc(**kwargs: Any) -> str:
        """Async dynamic tool execution closure."""
        return tool_func(**kwargs)

    tool = StructuredTool.from_function(
        func=tool_func,
        coroutine=tool_afunc,
        name=tool_name,
        description=description,
        args_schema=dynamic_args_schema,
    )
    return tool


def load_dynamic_superdocs_tools(client: SuperDocsClient) -> List[BaseTool]:
    """
    Fetch live tool declarations from the SuperDocs server (REST/MCP) and
    dynamically construct LangChain tools for each declaration.
    """
    declarations = client.get_tool_declarations()
    tools: List[BaseTool] = []
    for decl in declarations:
        try:
            tool = build_dynamic_tool(decl, client)
            tools.append(tool)
        except Exception as e:
            logger.error(f"Failed to build dynamic tool for '{decl.get('name')}': {e}")
    return tools


def load_tools_from_mcp_manifest(manifest: Dict[str, Any], client: SuperDocsClient) -> List[BaseTool]:
    """
    Load LangChain tools from an MCP (Model Context Protocol) tools list payload.
    Format: {"tools": [{"name": "...", "description": "...", "inputSchema": {...}}]}
    """
    mcp_tools = manifest.get("tools", [])
    tools: List[BaseTool] = []
    for item in mcp_tools:
        declaration = {
            "name": item.get("name"),
            "description": item.get("description"),
            "parameters": item.get("inputSchema", {}),
        }
        tools.append(build_dynamic_tool(declaration, client))
    return tools
