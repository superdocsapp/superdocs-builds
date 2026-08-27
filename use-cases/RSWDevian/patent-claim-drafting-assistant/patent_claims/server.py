from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any

from .core import ClaimValidationError, patent_from_payload
from .mcp import handle_mcp
from .store import ClaimStore
from .workflow import ClaimManager, ExportBlocked


class ClaimRequestHandler(BaseHTTPRequestHandler):
    manager: ClaimManager

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        return body

    def _export(self, patent_id: str, proposal_id: str, format_name: str) -> dict[str, Any]:
        result = self.manager.export(patent_id, proposal_id, format_name)
        if isinstance(result.get("artifact"), (bytes, bytearray)):
            result = {**result, "artifact": base64.b64encode(result["artifact"]).decode()}
        return result

    def _handle(self, method: str, body: dict[str, Any]) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if method == "POST" and path == "/mcp":
                return self._json(200, handle_mcp(self.manager, body))
            if method == "POST" and path == "/v1/builds/patent":
                return self._json(201, self.manager.create(patent_from_payload(body)))
            match = re.fullmatch(r"/v1/patents/([^/]+)/chat", path)
            if method == "POST" and match:
                return self._json(201, self.manager.propose(match.group(1), body["change_plan"]))
            match = re.fullmatch(r"/v1/patents/([^/]+)", path)
            if method == "GET" and match:
                patent = self.manager.store.get_patent(match.group(1))
                if patent is None:
                    raise ClaimValidationError("patent not found")
                return self._json(200, {"patent": patent.to_dict(), "content_hash": patent.content_hash()})
            match = re.fullmatch(r"/v1/proposals/([^/]+)", path)
            if method == "GET" and match:
                proposal = self.manager.store.get_proposal(match.group(1))
                if proposal is None:
                    raise ClaimValidationError("proposal not found")
                return self._json(200, proposal)
            match = re.fullmatch(r"/v1/proposals/([^/]+)/decision", path)
            if method == "POST" and match:
                return self._json(200, self.manager.decide(match.group(1), body["decision"], body["approver"]))
            match = re.fullmatch(r"/v1/patents/([^/]+)/export", path)
            if method == "POST" and match:
                return self._json(200, self._export(match.group(1), body["proposal_id"], body.get("format", "json")))
            return self._json(404, {"error": {"code": "NOT_FOUND", "message": "endpoint does not exist"}})
        except (ClaimValidationError, ExportBlocked, KeyError, ValueError) as error:
            status = 409 if isinstance(error, ExportBlocked) else 400
            code = getattr(error, "code", "INVALID_REQUEST")
            self._json(status, {"error": {"code": code, "message": str(error)}})

    def do_GET(self) -> None:
        self._handle("GET", {})

    def do_POST(self) -> None:
        try:
            self._handle("POST", self._body())
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"error": {"code": "INVALID_REQUEST", "message": str(error)}})

    def do_OPTIONS(self) -> None:
        self._json(204, {})

    def log_message(self, *_: Any) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = 8002, database: str = "patent-claims.sqlite3") -> ThreadingHTTPServer:
    ClaimRequestHandler.manager = ClaimManager(ClaimStore(database))
    return ThreadingHTTPServer((host, port), ClaimRequestHandler)


if __name__ == "__main__":
    create_server().serve_forever()
