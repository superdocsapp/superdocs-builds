from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Iterable


class InvoiceValidationError(ValueError):
    """Raised when an invoice cannot be normalized safely."""


@dataclass(frozen=True)
class SourceSnapshot:
    source_name: str
    source_hash: str
    record: dict[str, Any]
    source_text: str


_NUMBER = r"(?:[$€£]\s*)?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_NUMBER_RE = re.compile(_NUMBER)


def _money(value: Any, pointer: str) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise InvoiceValidationError(f"{pointer} must be a numeric string")
    cleaned = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise InvoiceValidationError(f"{pointer} must be a numeric string") from exc
    if not parsed.is_finite():
        raise InvoiceValidationError(f"{pointer} must be finite")
    return format(parsed, "f")


def _first(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> tuple[str, int] | None:
    match = re.search(pattern, text, flags)
    return (match.group(1).strip(), match.start()) if match else None


def _line_excerpt(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start:] if end < 0 else text[start:end]


def parse_invoice_text(text: str, source_name: str = "invoice.txt") -> dict[str, Any]:
    """Parse the intentionally small, auditable text fixture format.

    The parser records line pointers for every extracted value. It does not use
    an LLM and refuses to invent fields that are absent from the source.
    """
    if not isinstance(text, str) or not text.strip():
        raise InvoiceValidationError("invoice text must be non-empty")

    patterns = {
        "invoice_id": r"^\s*Invoice\s*(?:ID|Number|No\.?)\s*[:#-]?\s*([^\s]+)",
        "vendor": r"^\s*(?:Vendor|Supplier|Seller)\s*[:#-]\s*(.+?)\s*$",
        "invoice_date": r"^\s*Invoice\s*date\s*[:#-]\s*(\d{4}-\d{2}-\d{2})",
        "due_date": r"^\s*Due\s*date\s*[:#-]\s*(\d{4}-\d{2}-\d{2})",
        "currency": r"^\s*Currency\s*[:#-]\s*([A-Z]{3})",
        "declared_total": rf"^\s*(?:Total\s*due|Grand\s*total|Total|Amount\s*due)\s*[:#-]\s*({_NUMBER})",
        "payment_details": r"^\s*(?:Payment\s*details|Bank\s*account|Payment\s*account)\s*[:#-]\s*(.+?)\s*$",
    }
    values: dict[str, tuple[str, int]] = {}
    for key, pattern in patterns.items():
        found = _first(pattern, text)
        if found:
            values[key] = found

    required = ("invoice_id", "vendor", "invoice_date", "due_date", "declared_total", "payment_details")
    missing = [key for key in required if key not in values]
    if missing:
        raise InvoiceValidationError(f"missing source fields: {', '.join(missing)}")

    items: list[dict[str, Any]] = []
    item_pattern = re.compile(
        rf"^\s*(?:ITEM|LINE)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*({_NUMBER})\s*\|\s*({_NUMBER})\s*\|\s*({_NUMBER})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for index, match in enumerate(item_pattern.finditer(text)):
        excerpt = _line_excerpt(text, match.start())
        items.append(
            {
                "row_id": match.group(1).strip(),
                "description": match.group(2).strip(),
                "quantity": _money(match.group(3), f"line {index + 1} quantity"),
                "unit_price": _money(match.group(4), f"line {index + 1} unit_price"),
                "line_total": _money(match.group(5), f"line {index + 1} line_total"),
                "source_pointer": f"{source_name}:line:{text.count(chr(10), 0, match.start()) + 1}",
                "source_excerpt": excerpt,
            }
        )
    if not items:
        raise InvoiceValidationError("no line items found; use ITEM|row-id|description|quantity|unit|total")

    currency = values.get("currency", ("USD", 0))[0].upper()
    result = {
        "schema_version": "invoice.anomaly.v1",
        "source_name": source_name,
        "invoice_id": values["invoice_id"][0],
        "vendor": values["vendor"][0],
        "invoice_date": values["invoice_date"][0],
        "due_date": values["due_date"][0],
        "currency": currency,
        "declared_total": _money(values["declared_total"][0], "declared_total"),
        "payment_details": values["payment_details"][0],
        "line_items": items,
        "evidence": {
            key: {
                "pointer": f"{source_name}:line:{text.count(chr(10), 0, offset) + 1}",
                "excerpt": _line_excerpt(text, offset),
            }
            for key, (value, offset) in values.items()
        },
    }
    return canonicalize_invoice(result)


def canonicalize_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and copy an extracted invoice without hiding missing data."""
    if not isinstance(payload, dict):
        raise InvoiceValidationError("invoice must be an object")
    required = ("invoice_id", "vendor", "invoice_date", "due_date", "declared_total", "payment_details", "line_items")
    missing = [field for field in required if field not in payload]
    if missing:
        raise InvoiceValidationError(f"missing fields: {', '.join(missing)}")
    for field in ("invoice_id", "vendor", "payment_details"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise InvoiceValidationError(f"{field} must be a non-empty string")
    for field in ("invoice_date", "due_date"):
        try:
            date.fromisoformat(str(payload[field]))
        except ValueError as exc:
            raise InvoiceValidationError(f"{field} must be an ISO date") from exc
    currency = str(payload.get("currency", "USD")).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise InvoiceValidationError("currency must be an uppercase three-letter code")
    if not isinstance(payload["line_items"], list) or not payload["line_items"]:
        raise InvoiceValidationError("line_items must be a non-empty array")
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for index, item in enumerate(payload["line_items"]):
        pointer = f"payload.line_items[{index}]"
        if not isinstance(item, dict):
            raise InvoiceValidationError(f"{pointer} must be an object")
        for field in ("row_id", "description", "quantity", "unit_price", "line_total"):
            if field not in item or (isinstance(item[field], str) and not item[field].strip()):
                raise InvoiceValidationError(f"{pointer}.{field} is required")
        row_id = str(item["row_id"])
        if row_id in seen:
            raise InvoiceValidationError(f"duplicate line-item row_id: {row_id}")
        seen.add(row_id)
        copied = deepcopy(item)
        copied["row_id"] = row_id
        copied["description"] = str(item["description"])
        copied["quantity"] = _money(item["quantity"], f"{pointer}.quantity")
        copied["unit_price"] = _money(item["unit_price"], f"{pointer}.unit_price")
        copied["line_total"] = _money(item["line_total"], f"{pointer}.line_total")
        copied.setdefault("source_pointer", f"payload.line_items[{index}]")
        copied.setdefault("source_excerpt", json.dumps(item, sort_keys=True))
        items.append(copied)
    normalized = deepcopy(payload)
    normalized.update(
        {
            "schema_version": payload.get("schema_version", "invoice.anomaly.v1"),
            "currency": currency,
            "declared_total": _money(payload["declared_total"], "payload.declared_total"),
            "line_items": items,
        }
    )
    return normalized


def _canonical_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def create_snapshot(payload: dict[str, Any], source_text: str | None = None) -> SourceSnapshot:
    record = canonicalize_invoice(payload)
    text = source_text if source_text is not None else json.dumps(record, sort_keys=True)
    return SourceSnapshot(
        source_name=str(record.get("source_name", "invoice.json")),
        source_hash=hashlib.sha256(_canonical_bytes(record)).hexdigest(),
        record=record,
        source_text=text,
    )


def _evidence(snapshot: SourceSnapshot, pointer: str, excerpt: str) -> dict[str, str]:
    return {"source": snapshot.source_name, "pointer": pointer, "excerpt": excerpt}


def _finding(
    code: str,
    severity: str,
    message: str,
    snapshots: Iterable[SourceSnapshot],
    expected: str | None = None,
    observed: str | None = None,
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    evidence = evidence or []
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "invoice_ids": [snapshot.record["invoice_id"] for snapshot in snapshots],
        "expected": expected,
        "observed": observed,
        "evidence": evidence,
    }


def detect_anomalies(
    snapshots: list[SourceSnapshot],
    vendor_registry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run deterministic anomaly checks over a batch of immutable snapshots."""
    findings: list[dict[str, Any]] = []
    by_id: dict[str, list[SourceSnapshot]] = {}
    for snapshot in snapshots:
        by_id.setdefault(snapshot.record["invoice_id"], []).append(snapshot)
    for invoice_id, matches in sorted(by_id.items()):
        if len(matches) < 2:
            continue
        findings.append(
            _finding(
                "duplicate_invoice_id",
                "critical",
                f"Invoice ID {invoice_id} appears in {len(matches)} submitted documents.",
                matches,
                expected="unique invoice_id",
                observed=invoice_id,
                evidence=[
                    _evidence(
                        snapshot,
                        f"{snapshot.source_name}:invoice_id",
                        str(snapshot.record["invoice_id"]),
                    )
                    for snapshot in matches
                ],
            )
        )

    for snapshot in snapshots:
        record = snapshot.record
        computed = sum((Decimal(item["line_total"]) for item in record["line_items"]), Decimal("0"))
        declared = Decimal(record["declared_total"])
        if computed != declared:
            findings.append(
                _finding(
                    "total_mismatch",
                    "high",
                    f"Line-item total {computed:.2f} differs from declared total {declared:.2f}.",
                    [snapshot],
                    expected=f"{declared:.2f}",
                    observed=f"{computed:.2f}",
                    evidence=[
                        _evidence(snapshot, f"{snapshot.source_name}:declared_total", record["evidence"].get("declared_total", {}).get("excerpt", record["declared_total"])),
                        *[
                            _evidence(snapshot, str(item["source_pointer"]), str(item["source_excerpt"]))
                            for item in record["line_items"]
                        ],
                    ],
                )
            )

        if vendor_registry and record["vendor"] in vendor_registry:
            baseline = vendor_registry[record["vendor"]]
            if isinstance(baseline, dict):
                baseline = baseline.get("payment_details")
            if baseline is not None and str(baseline) != record["payment_details"]:
                findings.append(
                    _finding(
                        "payment_detail_change",
                        "critical",
                        f"Payment details for {record['vendor']} differ from the supplied baseline.",
                        [snapshot],
                        expected=str(baseline),
                        observed=record["payment_details"],
                        evidence=[
                            _evidence(
                                snapshot,
                                f"{snapshot.source_name}:payment_details",
                                record["evidence"].get("payment_details", {}).get("excerpt", record["payment_details"]),
                            )
                        ],
                    )
                )
    return findings
