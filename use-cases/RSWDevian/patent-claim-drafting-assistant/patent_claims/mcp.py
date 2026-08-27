from __future__ import annotations

import base64
from typing import Any

from .core import ClaimValidationError, patent_from_payload
from .workflow import ClaimManager, ExportBlocked

TOOLS = ["patent_start", "patent_get", "patent_chat", "patent_review", "patent_decide", "patent_export"]


def _export_result(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("artifact"), (bytes, bytearray)):
        return {**result, "artifact": base64.b64encode(result["artifact"]).decode()}
    return result


def handle_mcp(manager: ClaimManager, request: dict[str, Any]) -> dict[str, Any]:
    request_id, method, params = request.get("id"), request.get("method"), request.get("params", {})
    try:
        if method == "tools/list":
            result = {"tools": [{"name": name} for name in TOOLS]}
        elif method == "patent_start":
            result = manager.create(patent_from_payload(params["patent"]))
        elif method == "patent_get":
            patent = manager.store.get_patent(params["patent_id"])
            if patent is None:
                raise ClaimValidationError("patent not found")
            result = {"patent": patent.to_dict(), "content_hash": patent.content_hash()}
        elif method == "patent_chat":
            result = manager.propose(params["patent_id"], params["change_plan"])
        elif method == "patent_review":
            result = manager.store.get_proposal(params["proposal_id"])
        elif method == "patent_decide":
            result = manager.decide(params["proposal_id"], params["decision"], params["approver"])
        elif method == "patent_export":
            result = _export_result(manager.export(params["patent_id"], params["proposal_id"], params.get("format", "json")))
        else:
            raise ClaimValidationError("MCP method does not exist")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except (ExportBlocked, KeyError, ClaimValidationError, ValueError) as error:
        code = getattr(error, "code", "INVALID_REQUEST")
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": str(error)}}
