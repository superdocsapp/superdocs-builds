from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
import uuid
from typing import Any

from .core import create_source_snapshot, reconcile_invoice, render_invoice
from .exporters import export_bytes, invoice_html
from .live import LiveSuperDocsREST
from .store import DurableStore


class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InvoiceService:
    def __init__(self, store: DurableStore) -> None:
        self.store = store

    def start(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("invoice", payload)
        snapshot = create_source_snapshot(source)
        document = render_invoice(snapshot)
        run_id = str(uuid.uuid4())
        reconciliation = reconcile_invoice(snapshot, document)
        state = "awaiting_review" if reconciliation["findings"] else "passed"
        run = {"tenant_id": tenant_id, "build_id": "invoice-companion", "run_id": run_id, "state": state,
               "version": 1, "source_hash": snapshot.source_hash, "source_record": snapshot.record,
               "document": document, "reconciliation": reconciliation, "created_at": _now(), "updated_at": _now(),
               "items": {f"finding-{index}": finding for index, finding in enumerate(reconciliation["findings"])}
               }
        self.store.create_run(run)
        return self.summary(run)

    def get(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        return self.summary(run)

    def chat(self, tenant_id: str, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        document = payload.get("document", run["document"])
        snapshot = create_source_snapshot(run["source_record"])
        reconciliation = reconcile_invoice(snapshot, document)
        state = "awaiting_review" if reconciliation["findings"] else "passed"
        if not self.store.update_run(tenant_id, run_id, run["version"], state, document, reconciliation, _now()):
            raise ServiceError("STALE_RUN", "run changed; reload current state", 409)
        return self.get(tenant_id, run_id)

    def review(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        return {"run_id": run_id, "state": run["state"], "version": run["version"], "items": list(run["items"].values())}

    def decide(self, tenant_id: str, run_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        item = run["items"].get(item_id)
        if item is None:
            raise ServiceError("ITEM_NOT_FOUND", "review item does not exist", 404)
        decision = payload.get("decision")
        approver = payload.get("approver")
        if decision not in {"approved", "rejected", "accepted_exception"} or not isinstance(approver, str) or not approver:
            raise ServiceError("INVALID_DECISION", "decision and approver are required")
        if item["decision"] != "pending":
            raise ServiceError("ALREADY_DECIDED", "review item is already decided")
        remaining = [value for key, value in run["items"].items() if key != item_id and value["decision"] == "pending"]
        state = "partially_decided" if remaining else ("failed_with_accepted_exceptions" if decision == "accepted_exception" else "failed")
        if not self.store.decide(tenant_id, run_id, item_id, decision, approver, _now(), run["version"], state, _now()):
            raise ServiceError("STALE_RUN", "run changed; reload current state", 409)
        return self.get(tenant_id, run_id)

    def export(self, tenant_id: str, run_id: str, format_name: str = "json") -> dict[str, Any]:
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        if run["state"] != "passed":
            raise ServiceError("RECONCILIATION_GATE_BLOCKED", f"verified export blocked while run is {run['state']}", 409)
        existing = self.store.get_export(tenant_id, run_id)
        if existing:
            return existing
        mime_type, artifact_bytes = export_bytes(run["document"], format_name)
        artifact = {"format": format_name, "mime_type": mime_type, "content_base64": base64.b64encode(artifact_bytes).decode(), "source_hash": run["source_hash"]}
        artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
        certificate = {"status": "passed", "source_hash": run["source_hash"], "document_hash": artifact_hash,
                       "checked_fields": list(run["document"]["fields"].keys()), "findings": [], "decisions": [], "timestamp": _now()}
        self.store.save_export(tenant_id, run_id, artifact_hash, certificate, artifact, _now())
        return self.store.get_export(tenant_id, run_id) or {}

    def live_export(self, tenant_id: str, run_id: str, format_name: str = "docx", api_key: str | None = None) -> dict[str, Any]:
        """Load the verified invoice into SuperDocs and request its native export."""
        run = self.store.get_run(tenant_id, run_id)
        if run is None:
            raise ServiceError("RUN_NOT_FOUND", "run does not exist", 404)
        if run["state"] != "passed":
            raise ServiceError("RECONCILIATION_GATE_BLOCKED", f"verified export blocked while run is {run['state']}", 409)
        session_id = f"invoice-companion-{run_id}"
        client = LiveSuperDocsREST(api_key=api_key)
        loaded = client.chat(session_id, "Load this invoice exactly for export; do not change any values.", invoice_html(run["document"]), f"{run_id}:live-load")
        exported = client.export(session_id, format_name, f"{run_id}:live-export:{format_name}")
        return {"run_id": run_id, "session_id": session_id, "loaded": loaded, "export": exported, "source_hash": run["source_hash"]}

    @staticmethod
    def summary(run: dict[str, Any]) -> dict[str, Any]:
        return {"tenant_id": run["tenant_id"], "build_id": run["build_id"], "run_id": run["run_id"],
                "state": run["state"], "version": run["version"], "source_hash": run["source_hash"],
                "reconciliation": run["reconciliation"], "created_at": run["created_at"], "updated_at": run["updated_at"]}
