from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any

from .mcp import handle_mcp
from .model import Manual, ManualError, parse_mermaid
from .store import ManualStore
from .workflow import ExportBlocked, ManualManager


def manual_from_payload(payload: dict[str, Any]) -> Manual:
    data = dict(payload.get("manual", payload))
    diagrams = [parse_mermaid(item["diagram_id"], item["source_text"]) if "nodes" not in item else item for item in data["diagrams"]]
    data["diagrams"] = [item.__dict__ | {"edges": list(item.edges)} if hasattr(item, "edges") else item for item in diagrams]
    return Manual.from_dict(data)


class ManualRequestHandler(BaseHTTPRequestHandler):
    manager: ManualManager

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, sort_keys=True, default=lambda value: value.__dict__).encode()
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
        return json.loads(self.rfile.read(length) or b"{}")

    def _handle(self, method: str, body: dict[str, Any]) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if method == "POST" and path == "/mcp":
                return self._json(200, handle_mcp(self.manager, body))
            if method == "POST" and path == "/v1/builds/manual":
                return self._json(201, self.manager.create(manual_from_payload(body)))
            match = re.fullmatch(r"/v1/manuals/([^/]+)/chat", path)
            if method == "POST" and match:
                return self._json(201, self.manager.propose(match.group(1), body["change_plan"]))
            match = re.fullmatch(r"/v1/manuals/([^/]+)", path)
            if method == "GET" and match:
                manual = self.manager.store.get_manual(match.group(1))
                if manual is None: raise ManualError("manual not found")
                return self._json(200, {"manual": manual.to_dict(), "content_hash": manual.content_hash()})
            match = re.fullmatch(r"/v1/proposals/([^/]+)", path)
            if method == "GET" and match:
                proposal = self.manager.store.get_proposal(match.group(1))
                if proposal is None: raise ManualError("proposal not found")
                return self._json(200, proposal)
            match = re.fullmatch(r"/v1/proposals/([^/]+)/decision", path)
            if method == "POST" and match:
                return self._json(200, self.manager.decide(match.group(1), body["decision"], body["approver"]))
            match = re.fullmatch(r"/v1/manuals/([^/]+)/export", path)
            if method == "POST" and match:
                return self._json(200, self.manager.export(match.group(1), body["proposal_id"], body.get("format", "json")))
            return self._json(404, {"error": {"code": "NOT_FOUND", "message": "endpoint does not exist"}})
        except (ManualError, ExportBlocked, KeyError, ValueError) as error:
            code = getattr(error, "code", "INVALID_REQUEST")
            self._json(409 if isinstance(error, ExportBlocked) else 400, {"error": {"code": code, "message": str(error)}})

    def do_GET(self) -> None: self._handle("GET", {})
    def do_POST(self) -> None: self._handle("POST", self._body())
    def do_OPTIONS(self) -> None: self._json(204, {})
    def log_message(self, *_: Any) -> None: return


def create_server(host: str = "127.0.0.1", port: int = 8001, database: str = "iso-manual.sqlite3") -> ThreadingHTTPServer:
    ManualRequestHandler.manager = ManualManager(ManualStore(database))
    return ThreadingHTTPServer((host, port), ManualRequestHandler)


if __name__ == "__main__":
    create_server().serve_forever()
