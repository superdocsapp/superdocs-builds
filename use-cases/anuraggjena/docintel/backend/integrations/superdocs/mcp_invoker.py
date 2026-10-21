"""
MCP Tool Invoker.

Bridge between Python backend and SuperDocs MCP tools.
In production, this would connect to the MCP server via the protocol.
For now, it provides a testable interface.
"""

import os
import json
import asyncio
from typing import Dict, Any
import httpx

from backend.logging_config import get_logger
from backend.config import settings

logger = get_logger(__name__)


_client_lock = asyncio.Lock()
_mcp_client: httpx.AsyncClient | None = None


async def get_mcp_client() -> httpx.AsyncClient:
    """Get or initialize the shared HTTP client with connection pooling."""
    global _mcp_client
    if _mcp_client is None or _mcp_client.is_closed:
        async with _client_lock:
            if _mcp_client is None or _mcp_client.is_closed:
                _mcp_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(300.0, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
                )
    return _mcp_client


async def close_mcp_client() -> None:
    """Close the shared HTTP client."""
    global _mcp_client
    if _mcp_client is not None and not _mcp_client.is_closed:
        async with _client_lock:
            if _mcp_client is not None and not _mcp_client.is_closed:
                await _mcp_client.aclose()
                _mcp_client = None


async def invoke_mcp_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """
    Invoke SuperDocs MCP tool via JSON-RPC 2.0 protocol.

    This function bridges the Python backend with SuperDocs MCP tools.
    SuperDocs uses the MCP JSON-RPC 2.0 protocol, NOT REST endpoints.

    Args:
        tool_name: MCP tool name (e.g., "mcp__superdocs__init_session" or "init_session")
        **kwargs: Tool parameters

    Returns:
        Tool result as dictionary

    Raises:
        Exception: If tool invocation fails
    """
    # Extract the actual tool name (remove mcp__superdocs__ prefix)
    if tool_name.startswith("mcp__superdocs__"):
        mcp_tool = tool_name.replace("mcp__superdocs__", "")
    else:
        mcp_tool = tool_name

    logger.info(
        "invoking_superdocs_mcp_tool",
        tool=tool_name,
        mcp_tool=mcp_tool,
        params=list(kwargs.keys())
    )

    # SuperDocs MCP endpoint
    mcp_url = f"{settings.superdocs_api_url}/mcp"
    api_key = kwargs.pop("authorization", None) or settings.superdocs_api_key

    if not api_key:
        raise ValueError("SuperDocs API key not configured")

    # Remove None values from arguments (MCP server may reject null values)
    filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}

    # Prepare MCP JSON-RPC 2.0 request
    jsonrpc_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": mcp_tool,
            "arguments": filtered_kwargs
        }
    }

    # Prepare headers
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Log the exact request for debugging
    logger.debug(
        "mcp_request_details",
        url=mcp_url,
        method="POST",
        request_body=jsonrpc_request,
        headers={k: v for k, v in headers.items() if k != "Authorization"}
    )

    # Make JSON-RPC request using pooled client
    client = await get_mcp_client()
    try:
        response = await client.post(mcp_url, json=jsonrpc_request, headers=headers)

        # Log response for debugging (safely ignore logging failures)
        try:
            logger.debug(
                "mcp_response_details",
                status=response.status_code,
                response_body=response.text[:500] if response.text else None
            )
        except Exception:
            pass

        response.raise_for_status()
        jsonrpc_response = response.json()

        # Check for JSON-RPC error
        if "error" in jsonrpc_response:
            error = jsonrpc_response["error"]
            error_msg = f"MCP error {error.get('code')}: {error.get('message')}"
            logger.error(
                "superdocs_mcp_error",
                tool=tool_name,
                error_code=error.get("code"),
                error_message=error.get("message")
            )
            raise Exception(error_msg)

        # Extract result from JSON-RPC response
        if "result" not in jsonrpc_response:
            raise Exception(f"Invalid MCP response: missing 'result' field")

        mcp_result = jsonrpc_response["result"]

        # Check for MCP-level errors
        if mcp_result.get("isError", False):
            error_text = mcp_result.get("content", [{}])[0].get("text", "Unknown error")
            logger.error("superdocs_mcp_tool_error", tool=tool_name, error=error_text)
            raise Exception(f"MCP tool error: {error_text}")

        # Extract structured content (the actual result data)
        if "structuredContent" in mcp_result:
            result = mcp_result["structuredContent"]
        elif "content" in mcp_result and len(mcp_result["content"]) > 0:
            # Fallback: parse JSON from text content
            content_text = mcp_result["content"][0].get("text", "{}")
            result = json.loads(content_text)
        else:
            result = mcp_result

        logger.info(
            "superdocs_mcp_tool_success",
            tool=tool_name,
            status=response.status_code
        )

        return result

    except httpx.HTTPStatusError as exc:
        logger.error(
            "superdocs_http_error",
            tool=tool_name,
            status=exc.response.status_code,
            error=exc.response.text
        )
        raise Exception(f"SuperDocs MCP HTTP error {exc.response.status_code}: {exc.response.text}") from exc

    except httpx.TimeoutException as exc:
        logger.error("superdocs_timeout", tool=tool_name)
        raise TimeoutError(f"SuperDocs MCP request timed out") from exc

    except httpx.ConnectError as exc:
        logger.error("superdocs_connection_error", tool=tool_name)
        raise ConnectionError(f"Failed to connect to SuperDocs MCP") from exc

    except Exception as exc:
        logger.error("superdocs_unexpected_error", tool=tool_name, error=str(exc))
        raise
