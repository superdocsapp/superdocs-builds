from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .core import SourceSnapshot, reconcile_invoice
from .transport import FakeSuperDocsTransport


class ExportBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ReviewItem:
    item_id: str
    finding: dict[str, Any]
    decision: str = "pending"
    approver: str | None = None


class InvoiceRun:
    """Small durable-shaped state machine for reconciliation review and export."""

    def __init__(self, snapshot: SourceSnapshot, document: dict[str, Any], transport: FakeSuperDocsTransport) -> None:
        self.snapshot = snapshot
        self.document = deepcopy(document)
        self.transport = transport
        self.reconciliation = reconcile_invoice(snapshot, self.document)
        self.items = {
            f"finding-{index}": ReviewItem(f"finding-{index}", finding)
            for index, finding in enumerate(self.reconciliation["findings"])
        }
        self.state = "awaiting_review" if self.items else "passed"

    def submit(self, run_id: str) -> None:
        self.transport.upload(f"{run_id}:upload", self.document)
        self.transport.chat(f"{run_id}:chat", self.reconciliation)

    def decide(self, item_id: str, decision: str, approver: str, run_id: str) -> None:
        if item_id not in self.items:
            raise KeyError(f"unknown review item: {item_id}")
        if decision not in {"approved", "rejected", "accepted_exception"}:
            raise ValueError("decision must be approved, rejected, or accepted_exception")
        item = self.items[item_id]
        if item.decision != "pending":
            raise ValueError(f"review item already decided: {item_id}")
        self.transport.approve(f"{run_id}:approve:{item_id}", {"item_id": item_id, "decision": decision, "approver": approver})
        item.decision = decision
        item.approver = approver
        if any(review.decision == "pending" for review in self.items.values()):
            self.state = "partially_decided"
        elif any(review.decision == "accepted_exception" for review in self.items.values()):
            self.state = "failed_with_accepted_exceptions"
        else:
            # A reviewer decision records disposition; it cannot turn a hard mismatch into a pass.
            self.state = "failed"

    def export_verified(self, run_id: str) -> dict[str, Any]:
        if self.state != "passed":
            raise ExportBlocked("RECONCILIATION_GATE_BLOCKED", f"verified export blocked while run is {self.state}")
        return self.transport.export(f"{run_id}:export", self.document)
