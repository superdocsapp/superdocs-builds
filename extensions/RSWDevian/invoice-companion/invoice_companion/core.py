# Domain logic for invoice-companion extension.
# This module is responsible for validating, canonicalizing, and reconciling invoice data against a source snapshot.
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any


class InvoiceValidationError(ValueError):
    """Raised when source data cannot satisfy invoice.v1."""


@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: str
    source_hash: str
    record: dict[str, Any]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    location: str
    expected: str | None
    observed: str | None
    source_pointer: str | None
    message: str


_AMOUNT_FIELDS = ("unit_price", "line_total", "subtotal", "tax", "total")
_NUMERIC_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:[$€£]\s*)?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![A-Za-z0-9])")


def _amount(value: Any, pointer: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise InvoiceValidationError(f"{pointer} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise InvoiceValidationError(f"{pointer} must be a decimal string") from exc
    if not parsed.is_finite():
        raise InvoiceValidationError(f"{pointer} must be finite")
    return value


def canonicalize_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and deep-copy an invoice without deriving or rewriting source values."""
    if not isinstance(payload, dict):
        raise InvoiceValidationError("invoice must be an object")
    required = (
        "schema_version", "invoice_id", "issue_date", "due_date", "seller", "buyer",
        "currency", "line_items", "subtotal", "tax", "total", "payment_terms",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise InvoiceValidationError(f"missing fields: {', '.join(missing)}")
    if payload["schema_version"] != "invoice.v1":
        raise InvoiceValidationError("schema_version must be invoice.v1")
    for field in ("invoice_id", "currency", "payment_terms"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise InvoiceValidationError(f"{field} must be a non-empty string")
    if not re.fullmatch(r"[A-Z]{3}", payload["currency"]):
        raise InvoiceValidationError("currency must be an uppercase ISO-style code")
    for field in ("issue_date", "due_date"):
        try:
            date.fromisoformat(payload[field])
        except (TypeError, ValueError) as exc:
            raise InvoiceValidationError(f"{field} must be an ISO date") from exc
    for party in ("seller", "buyer"):
        if not isinstance(payload[party], dict) or not all(
            isinstance(payload[party].get(key), str) and payload[party][key].strip()
            for key in ("name", "tax_id")
        ):
            raise InvoiceValidationError(f"{party} must contain name and tax_id strings")
    if not isinstance(payload["line_items"], list) or not payload["line_items"]:
        raise InvoiceValidationError("line_items must be a non-empty array")
    seen: set[str] = set()
    for index, item in enumerate(payload["line_items"]):
        pointer = f"payload.line_items[{index}]"
        if not isinstance(item, dict):
            raise InvoiceValidationError(f"{pointer} must be an object")
        for field in ("row_id", "description", "quantity", "source_pointer"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise InvoiceValidationError(f"{pointer}.{field} must be a non-empty string")
        if item["row_id"] in seen:
            raise InvoiceValidationError(f"duplicate row_id: {item['row_id']}")
        seen.add(item["row_id"])
        _amount(item["quantity"], f"{pointer}.quantity")
        for field in ("unit_price", "line_total"):
            _amount(item[field], f"{pointer}.{field}")
    for field in _AMOUNT_FIELDS[2:]:
        _amount(payload[field], f"payload.{field}")
    return deepcopy(payload)


def _canonical_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def create_source_snapshot(payload: dict[str, Any]) -> SourceSnapshot:
    record = canonicalize_invoice(payload)
    digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    return SourceSnapshot(record["schema_version"], digest, record)


def render_invoice(snapshot: SourceSnapshot) -> dict[str, Any]:
    """Build both document table values and the structured extract from the snapshot."""
    source = snapshot.record
    table = [
        {"row_id": item["row_id"], "description": item["description"], "quantity": item["quantity"],
         "unit_price": item["unit_price"], "line_total": item["line_total"],
         "source_pointer": item["source_pointer"]}
        for item in source["line_items"]
    ]
    return {
        "source_hash": snapshot.source_hash,
        "fields": {field: source[field] for field in ("invoice_id", "issue_date", "due_date", "currency", "subtotal", "tax", "total", "payment_terms")},
        "seller": deepcopy(source["seller"]),
        "buyer": deepcopy(source["buyer"]),
        "table": table,
        "structured_extract": deepcopy(source),
        "narrative": f"Invoice {source['invoice_id']} totals {source['currency']} {source['total']} and is due {source['due_date']}.",
    }


def _normalise_number(value: str) -> Decimal:
    return Decimal(value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip())


def reconcile_invoice(snapshot: SourceSnapshot, document: dict[str, Any]) -> dict[str, Any]:
    """Compare document observations to source facts; never recompute authoritative totals."""
    source = snapshot.record
    findings: list[Finding] = []
    observed_fields = document.get("fields", {})
    scalar_fields = ("invoice_id", "issue_date", "due_date", "currency", "subtotal", "tax", "total", "payment_terms")
    for field in scalar_fields:
        expected = str(source[field])
        observed = observed_fields.get(field)
        if observed is None:
            findings.append(Finding("missing", "hard_failure", f"fields.{field}", expected, None, f"payload.{field}", f"Missing {field}"))
        elif field in _AMOUNT_FIELDS:
            try:
                equal = _normalise_number(str(observed)) == _normalise_number(expected)
            except InvalidOperation:
                equal = False
            if not equal:
                findings.append(Finding("mismatch", "hard_failure", f"fields.{field}", expected, str(observed), f"payload.{field}", f"{field} differs from source"))
        elif str(observed) != expected:
            findings.append(Finding("mismatch", "hard_failure", f"fields.{field}", expected, str(observed), f"payload.{field}", f"{field} differs from source"))

    source_rows = {item["row_id"]: item for item in source["line_items"]}
    rows = document.get("table", [])
    seen_rows: set[str] = set()
    for index, row in enumerate(rows):
        row_id = row.get("row_id") if isinstance(row, dict) else None
        location = f"table[{index}]"
        if row_id not in source_rows:
            findings.append(Finding("unsupported", "hard_failure", location, None, str(row_id), None, "Document row has no canonical source row"))
            continue
        seen_rows.add(row_id)
        expected_row = source_rows[row_id]
        for field in ("description", "quantity", "unit_price", "line_total"):
            expected = str(expected_row[field])
            observed = row.get(field)
            equal = str(observed) == expected
            if field in ("quantity", "unit_price", "line_total") and observed is not None:
                try:
                    equal = _normalise_number(str(observed)) == _normalise_number(expected)
                except InvalidOperation:
                    equal = False
            if not equal:
                row_index = source["line_items"].index(expected_row)
                findings.append(Finding("mismatch", "hard_failure", f"{location}.{field}", expected, None if observed is None else str(observed), f"payload.line_items[{row_index}].{field}", f"Line item {row_id} {field} differs from source"))
    for row_id, row in source_rows.items():
        if row_id not in seen_rows:
            findings.append(Finding("missing", "hard_failure", f"table[{row_id}]", row["line_total"], None, row["source_pointer"], "Canonical line item is missing from document table"))

    known_values = [(str(source[field]), f"payload.{field}") for field in ("subtotal", "tax", "total")]
    for row in source["line_items"]:
        row_index = source["line_items"].index(row)
        known_values.extend(
            (str(row[field]), f"payload.line_items[{row_index}].{field}")
            for field in ("quantity", "unit_price", "line_total")
        )
    narrative = str(document.get("narrative", ""))
    # Identifiers and dates are metadata, not monetary/quantity figures in the prose scan.
    narrative = narrative.replace(str(source["invoice_id"]), "")
    narrative = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", narrative)
    for index, token in enumerate(_NUMERIC_TOKEN.findall(narrative)):
        try:
            token_value = _normalise_number(token)
        except InvalidOperation:
            token_value = None
        matches = [(value, pointer) for value, pointer in known_values if token_value is not None and _normalise_number(value) == token_value]
        if not matches:
            findings.append(Finding("unsupported", "hard_failure", f"narrative.figure[{index}]", None, token, None, "Narrative figure cannot be traced to a canonical value"))
    status = "passed" if not findings else "failed"
    return {"status": status, "source_hash": snapshot.source_hash, "findings": [finding.__dict__ for finding in findings]}
