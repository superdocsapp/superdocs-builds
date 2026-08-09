from __future__ import annotations

from typing import Any

from .model import Manual
from .workflow import ExportBlocked, ManualManager


TOOLS = ["manual_start", "manual_get", "manual_chat", "manual_review", "manual_decide", "manual_export"]


def handle_mcp(manager: ManualManager, request: dict[str, Any]) -> dict[str, Any]:
    request_id, method, params = request.get("id"), request.get("method"), request.get("params", {})
    try:
        if method == "tools/list": result = {"tools": [{"name": name} for name in TOOLS]}
        elif method == "manual_start": result = manager.create(Manual.from_dict(params["manual"]))
        elif method == "manual_get":
            manual = manager.store.get_manual(params["manual_id"])
            if manual is None: raise ValueError("manual not found")
            result = {"manual": manual.to_dict(), "content_hash": manual.content_hash()}
        elif method == "manual_chat": result = manager.propose(params["manual_id"], params["change_plan"])
        elif method == "manual_review": result = manager.store.get_proposal(params["proposal_id"])
        elif method == "manual_decide": result = manager.decide(params["proposal_id"], params["decision"], params["approver"])
        elif method == "manual_export": result = manager.export(params["manual_id"], params["proposal_id"], params.get("format", "json"))
        else: raise ValueError("MCP method does not exist")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ExportBlocked, KeyError, ValueError) as error:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": getattr(error, "code", "INVALID_REQUEST"), "message": str(error)}}
