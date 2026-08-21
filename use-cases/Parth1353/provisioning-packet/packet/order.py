"""The order record, and the field registry that governs it.

One signed order feeds six documents and two audiences. Everything that makes
that safe lives here:

* **The registry declares every field once** — its label, how it formats, and
  who is allowed to see it. A field marked ``internal`` cannot reach a
  customer-facing document, because the renderer resolves it to a redaction
  rather than a value. That is a property of the data, not of remembering to
  leave it out of six templates.
* **Values are formatted in one place.** A bandwidth is written the same way in
  the survey request and the acceptance test plan because both ask the registry,
  and change propagation can therefore search for a value it knows the exact
  spelling of.
* **The record is validated on load** with errors that name the field and the
  fix, because a provisioning pack built from a malformed order is worse than
  no pack.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Audience = Literal["both", "internal"]


class OrderError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    path: str
    label: str
    audience: Audience = "both"
    fmt: str = "text"
    required: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# The registry. Adding a field to a pack is an entry here plus a placeholder in
# a template — no renderer change, no audience logic anywhere else.
# ---------------------------------------------------------------------------

REGISTRY: tuple[Field, ...] = (
    # -- the instrument
    Field("order.reference", "Service order", required=True),
    Field("order.msa_reference", "Master agreement", required=True),
    Field("order.signed_date", "Order signed", fmt="date", required=True),
    Field("order.version", "Pack version"),
    # -- parties
    Field("customer.legal_name", "Customer", required=True),
    Field("customer.trading_name", "Trading as"),
    Field("customer.billing_reference", "Customer PO"),
    Field("customer.primary_contact.name", "Customer contact", required=True),
    Field("customer.primary_contact.role", "Contact role"),
    Field("customer.primary_contact.email", "Contact email", required=True),
    Field("customer.primary_contact.phone", "Contact phone"),
    Field("customer.site_contact.name", "Site contact"),
    Field("customer.site_contact.phone", "Site contact phone"),
    Field("supplier.legal_name", "Supplier", required=True),
    Field("supplier.delivery_manager.name", "Delivery manager", required=True),
    Field("supplier.delivery_manager.email", "Delivery manager email", required=True),
    Field("supplier.noc_number", "NOC (24×7)"),
    # -- the ordered service
    Field("service.product", "Product", required=True),
    Field("service.circuit_id", "Circuit ID", required=True),
    Field("service.bandwidth_mbps", "Bandwidth", fmt="bandwidth", required=True),
    Field("service.cir_mbps", "Committed information rate", fmt="bandwidth"),
    Field("service.handoff", "Customer handoff", required=True),
    Field("service.vlan_mode", "VLAN mode"),
    Field("service.mtu", "MTU", fmt="int"),
    Field("service.diversity", "Route diversity", fmt="diversity", required=True),
    Field("service.protection", "Protection scheme"),
    Field("service.cpe.model", "CPE model"),
    Field("service.cpe.count", "CPE units", fmt="int"),
    Field("service.cpe.managed", "CPE managed by supplier", fmt="yesno"),
    # -- sites
    Field("sites.a.label", "A-end site", required=True),
    Field("sites.a.address", "A-end address", required=True),
    Field("sites.a.room", "A-end room"),
    Field("sites.a.access_hours", "A-end access hours"),
    Field("sites.a.escort_required", "A-end escort required", fmt="yesno"),
    Field("sites.a.power", "A-end power provision"),
    Field("sites.b.label", "B-end site", required=True),
    Field("sites.b.address", "B-end address", required=True),
    Field("sites.b.room", "B-end room"),
    Field("sites.b.access_hours", "B-end access hours"),
    Field("sites.b.escort_required", "B-end escort required", fmt="yesno"),
    Field("sites.b.power", "B-end power provision"),
    # -- delivery
    Field("delivery.rfs_date", "Ready for service", fmt="date", required=True),
    Field("delivery.survey_date", "Site survey", fmt="date"),
    Field("delivery.install_date", "Installation", fmt="date"),
    Field("delivery.cutover_window", "Cutover window"),
    Field("delivery.acceptance_days", "Acceptance period", fmt="days"),
    Field("delivery.liquidated_damages", "Delay compensation"),
    # -- commercial
    Field("commercial.currency", "Currency"),
    Field("commercial.mrc", "Monthly recurring charge", fmt="money", required=True),
    Field("commercial.nrc", "One-off charge", fmt="money", required=True),
    Field("commercial.term_months", "Committed term", fmt="months", required=True),
    Field("commercial.payment_terms_days", "Payment terms", fmt="days"),
    # -- service levels
    Field("sla.availability_pct", "Committed availability", fmt="pct", required=True),
    Field("sla.mttr_hours", "Mean time to repair", fmt="hours"),
    Field("sla.latency_ms", "Round-trip latency", fmt="ms"),
    Field("sla.jitter_ms", "Jitter", fmt="ms"),
    Field("sla.packet_loss_pct", "Packet loss", fmt="pct4"),
    Field("sla.credit_cap_pct", "Service credit cap", fmt="pct"),
    # -- internal only. These exist in the record, are used by internal
    #    documents, and are structurally unable to reach a customer pack.
    Field("internal.wholesale_circuit_ref", "Wholesale circuit", audience="internal",
          note="supplier's upstream reference — never shown to the customer"),
    Field("internal.wholesale_cost_mrc", "Wholesale cost (MRC)", audience="internal", fmt="money"),
    Field("internal.gross_margin_pct", "Gross margin", audience="internal", fmt="pct"),
    Field("internal.provisioning_notes", "Provisioning notes", audience="internal"),
    Field("internal.build_risk", "Build risk", audience="internal"),
    Field("internal.escalation_l1", "Escalation L1", audience="internal"),
    Field("internal.escalation_l2", "Escalation L2", audience="internal"),
    Field("internal.margin_floor_note", "Margin floor", audience="internal"),
)

BY_PATH: dict[str, Field] = {f.path: f for f in REGISTRY}
INTERNAL_PATHS: frozenset[str] = frozenset(f.path for f in REGISTRY if f.audience == "internal")

REDACTION = "[withheld — internal]"


# ---------------------------------------------------------------------------


class Order:
    """A loaded, validated order record."""

    def __init__(self, data: dict[str, Any], *, source: str = "<memory>") -> None:
        self.data = data
        self.source = source
        self.validate()

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> Order:
        path = Path(path)
        if not path.exists():
            raise OrderError(f"no order record at {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OrderError(f"{path}: not valid YAML — {exc}") from exc
        if not isinstance(data, dict):
            raise OrderError(f"{path}: the order record must be a mapping at the top level")
        return cls(data, source=str(path))

    def save(self, path: Path | str) -> None:
        Path(path).write_text(
            yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    def copy(self) -> Order:
        import copy as _copy

        return Order(_copy.deepcopy(self.data), source=self.source)

    # -- access ------------------------------------------------------------

    def raw(self, path: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def has(self, path: str) -> bool:
        sentinel = object()
        return self.raw(path, sentinel) is not sentinel

    def set(self, path: str, value: Any) -> Any:
        """Set a field, returning the previous value. Refuses unknown paths —
        a typo in a change request must not silently write a field nothing
        renders."""
        if path not in BY_PATH:
            near = [p for p in BY_PATH if path.split(".")[-1] in p]
            raise OrderError(
                f"{path!r} is not a declared field"
                + (f". Did you mean: {', '.join(sorted(near)[:4])}?" if near else "")
            )
        node = self.data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        before = node.get(parts[-1])
        node[parts[-1]] = value
        return before

    def value(self, path: str, *, audience: str = "internal") -> str:
        """The rendered value for one field, for one audience.

        An internal field asked for by a customer document resolves to the
        redaction marker. There is no code path that returns the real value to
        the wrong audience, because the check is here rather than in a template.
        """
        spec = BY_PATH.get(path)
        if spec is None:
            raise OrderError(f"{path!r} is not a declared field")
        if spec.audience == "internal" and audience == "customer":
            return REDACTION
        raw = self.raw(path)
        if raw is None or raw == "":
            return "—"
        return format_value(raw, spec.fmt)

    def label(self, path: str) -> str:
        spec = BY_PATH.get(path)
        return spec.label if spec else path

    # -- validation --------------------------------------------------------

    def validate(self) -> None:
        problems: list[str] = []
        for spec in REGISTRY:
            if spec.required and not _present(self.raw(spec.path)):
                problems.append(f"  {spec.path} ({spec.label}) is required and missing")

        for path in ("delivery.rfs_date", "delivery.survey_date", "delivery.install_date",
                     "order.signed_date"):
            raw = self.raw(path)
            if raw is not None and not _is_date(raw):
                problems.append(f"  {path} must be a date (YYYY-MM-DD), got {raw!r}")

        bw = self.raw("service.bandwidth_mbps")
        if bw is not None and (not isinstance(bw, (int, float)) or bw <= 0):
            problems.append(f"  service.bandwidth_mbps must be a positive number, got {bw!r}")

        cir = self.raw("service.cir_mbps")
        if isinstance(bw, (int, float)) and isinstance(cir, (int, float)) and cir > bw:
            problems.append(
                f"  service.cir_mbps ({cir}) exceeds service.bandwidth_mbps ({bw}) — "
                "a committed rate above the port speed cannot be delivered"
            )

        div = self.raw("service.diversity")
        if div is not None and str(div).lower() not in {"none", "dual", "diverse", "single"}:
            problems.append(
                f"  service.diversity must be one of none/single/dual/diverse, got {div!r}"
            )

        order_of_dates = [
            ("order.signed_date", "delivery.survey_date"),
            ("delivery.survey_date", "delivery.install_date"),
            ("delivery.install_date", "delivery.rfs_date"),
        ]
        for earlier, later in order_of_dates:
            a, b = self.raw(earlier), self.raw(later)
            if _is_date(a) and _is_date(b) and _as_date(a) > _as_date(b):
                problems.append(
                    f"  {later} ({b}) is before {earlier} ({a}) — the delivery plan is impossible"
                )

        unknown = [p for p in _walk(self.data) if p not in BY_PATH]
        for path in sorted(unknown):
            problems.append(
                f"  {path} is in the record but not declared in the registry — it will "
                f"render nowhere. Add it to packet/order.py or remove it."
            )

        if problems:
            raise OrderError(
                f"{self.source} is not a usable order record:\n" + "\n".join(problems)
            )

    # -- summaries ---------------------------------------------------------

    def internal_values(self) -> dict[str, str]:
        return {
            p: format_value(self.raw(p), BY_PATH[p].fmt)
            for p in sorted(INTERNAL_PATHS)
            if _present(self.raw(p))
        }

    def fingerprint(self) -> str:
        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(self.data, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Formatting. One spelling per value, everywhere it appears — which is what
# makes "find the old value and replace it" a safe instruction to give.
# ---------------------------------------------------------------------------


def format_value(raw: Any, fmt: str) -> str:
    if raw is None:
        return "—"
    if fmt == "money":
        return f"{float(raw):,.2f}"
    if fmt == "bandwidth":
        mbps = float(raw)
        if mbps >= 1000 and mbps % 1000 == 0:
            return f"{int(mbps // 1000)} Gbps"
        return f"{mbps:g} Mbps"
    if fmt == "pct":
        return f"{float(raw):g}%"
    if fmt == "pct4":
        return f"{float(raw):.4g}%"
    if fmt == "ms":
        return f"{float(raw):g} ms"
    if fmt == "hours":
        return f"{float(raw):g} hours"
    if fmt == "days":
        return f"{int(raw)} days"
    if fmt == "months":
        return f"{int(raw)} months"
    if fmt == "int":
        return f"{int(raw)}"
    if fmt == "yesno":
        return "Yes" if raw in (True, "yes", "Yes", "true", 1) else "No"
    if fmt == "diversity":
        return {"none": "None — single path", "single": "None — single path"}.get(
            str(raw).lower(), "Dual path — physically diverse"
        )
    if fmt == "date":
        return _as_date(raw).strftime("%d %B %Y") if _is_date(raw) else str(raw)
    return str(raw)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date(raw: Any) -> bool:
    if isinstance(raw, (dt.date, dt.datetime)):
        return True
    return isinstance(raw, str) and bool(_DATE.match(raw.strip()))


def _as_date(raw: Any) -> dt.date:
    if isinstance(raw, dt.datetime):
        return raw.date()
    if isinstance(raw, dt.date):
        return raw
    return dt.date.fromisoformat(str(raw).strip())


def _present(raw: Any) -> bool:
    return raw is not None and raw != "" and raw != []


def _walk(node: Any, prefix: str = "") -> list[str]:
    """Every leaf path in the record, for the undeclared-field check."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.extend(_walk(v, path))
            else:
                out.append(path)
    return out
