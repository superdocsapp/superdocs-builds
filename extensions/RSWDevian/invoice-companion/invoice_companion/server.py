from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any

from .service import InvoiceService, ServiceError
from .store import DurableStore
from .mcp import handle_mcp
from .live import LiveSuperDocsError


class InvoiceRequestHandler(BaseHTTPRequestHandler):
    service: InvoiceService

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tenant-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _handle(self, method: str, body: dict[str, Any]) -> None:
        tenant = self.headers.get("X-Tenant-ID", "default")
        path = self.path.split("?", 1)[0]
        try:
            if method == "POST" and path == "/mcp":
                return self._json(200, handle_mcp(self.service, body, tenant))
            if method == "POST" and path == "/v1/builds/invoice":
                return self._json(201, self.service.start(tenant, body))
            match = re.fullmatch(r"/v1/runs/([^/]+)/chat", path)
            if method == "POST" and match:
                return self._json(200, self.service.chat(tenant, match.group(1), body))
            match = re.fullmatch(r"/v1/runs/([^/]+)/review/([^/]+)", path)
            if method == "POST" and match:
                return self._json(200, self.service.decide(tenant, match.group(1), match.group(2), body))
            match = re.fullmatch(r"/v1/runs/([^/]+)/export", path)
            if method == "POST" and match:
                return self._json(200, self.service.export(tenant, match.group(1), body.get("format", "json")))
            match = re.fullmatch(r"/v1/runs/([^/]+)/live-export", path)
            if method == "POST" and match:
                return self._json(200, self.service.live_export(tenant, match.group(1), body.get("format", "docx")))
            match = re.fullmatch(r"/v1/runs/([^/]+)/review", path)
            if method == "GET" and match:
                return self._json(200, self.service.review(tenant, match.group(1)))
            match = re.fullmatch(r"/v1/runs/([^/]+)", path)
            if method == "GET" and match:
                return self._json(200, self.service.get(tenant, match.group(1)))
            return self._json(404, {"error": {"code": "NOT_FOUND", "message": "endpoint does not exist"}})
        except (ServiceError, LiveSuperDocsError, ValueError, json.JSONDecodeError) as error:
            if isinstance(error, ServiceError):
                status, code, message = error.status, error.code, error.message
            elif isinstance(error, LiveSuperDocsError):
                status, code, message = 502, "LIVE_SUPERDOCS_ERROR", str(error)
            else:
                status, code, message = 400, "INVALID_REQUEST", str(error)
            self._json(status, {"error": {"code": code, "message": message}})

    def do_GET(self) -> None:
        self._handle("GET", {})

    def do_POST(self) -> None:
        self._handle("POST", self._body())

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tenant-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, *_: Any) -> None:
        return


def create_server(host: str = "127.0.0.1", port: int = 8000, database: str = "invoice-companion.sqlite3") -> ThreadingHTTPServer:
    InvoiceRequestHandler.service = InvoiceService(DurableStore(database))
    return ThreadingHTTPServer((host, port), InvoiceRequestHandler)


if __name__ == "__main__":
    create_server().serve_forever()
