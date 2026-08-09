from __future__ import annotations

from typing import Any

from .service import InvoiceService, ServiceError


TOOLS = [
    "invoice_start",
    "invoice_get",
    "invoice_review",
    "invoice_decide",
    "invoice_export",
]


def handle_mcp(service: InvoiceService, request: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
    """Handle the small JSON-RPC surface with REST-equivalent operations and refusals."""
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})
    try:
        if method == "tools/list":
            result = {"tools": [{"name": tool} for tool in TOOLS]}
        elif method == "invoice_start":
            result = service.start(tenant_id, params)
        elif method == "invoice_get":
            result = service.get(tenant_id, params["run_id"])
        elif method == "invoice_review":
            result = service.review(tenant_id, params["run_id"])
        elif method == "invoice_decide":
            result = service.decide(tenant_id, params["run_id"], params["item_id"], params)
        elif method == "invoice_export":
            result = service.export(tenant_id, params["run_id"], params.get("format", "json"))
        else:
            raise ServiceError("METHOD_NOT_FOUND", "MCP method does not exist", 404)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ServiceError, KeyError, ValueError) as error:
        if isinstance(error, ServiceError):
            code, message = error.code, error.message
        else:
            code, message = "INVALID_REQUEST", str(error)
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
