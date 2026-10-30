"""
Durable SQLite persistence for the Nursing Handoff Assembler (LIMITATIONS §3 remediation).

Gate confirmations and the full packet state now survive server restarts: every
mutation is written to a local SQLite table and rehydrated at startup. Pure
stdlib (sqlite3 + json + dataclasses) — no new dependencies are introduced.

Semantics:
- `serialize_assembler` / `restore_assembler` are exact round-trips: a restored
  assembler has the same demographics, SBAR, medications, gates (including the
  first-nurse-wins attributions), and source documents as the original.
- `save_state` upserts a single row per state id; the caller owns WHEN to save
  (server.py persists after every gate confirmation and reset).
- Corrupt or missing state never crashes startup: callers fall back to the
  pristine default assembler.
"""
import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from clinical_pipeline import (
    ClinicalPacketAssembler,
    MedicationItem,
    PatientDemographics,
    SBARData,
    SafetyGatekeeper,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assembler_state (
    id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SCHEMA)
    return conn


def serialize_assembler(inst: ClinicalPacketAssembler) -> str:
    """Serialize the full assembler state (packet + gates) to a JSON string."""
    return json.dumps(
        {
            "demographics": asdict(inst.demographics),
            "sbar": asdict(inst.sbar) if inst.sbar else None,
            "allergies": inst.allergies,
            "medications": [asdict(m) for m in inst.medications],
            "gates": asdict(inst.gates),
            "source_documents": inst.source_documents,
            "active_orders": inst.active_orders,
            "pending_labs": inst.pending_labs,
            "mobility_isolation": inst.mobility_isolation,
        },
        default=str,
    )


def restore_assembler(state_json: str) -> ClinicalPacketAssembler:
    """Rehydrate an assembler from `serialize_assembler` output (exact round-trip)."""
    data = json.loads(state_json)

    inst = ClinicalPacketAssembler(demographics=PatientDemographics(**data["demographics"]))
    if data.get("sbar"):
        inst.sbar = SBARData(**data["sbar"])
    inst.allergies = list(data.get("allergies", []))
    inst.medications = [MedicationItem(**m) for m in data.get("medications", [])]
    inst.gates = SafetyGatekeeper(**(data.get("gates") or {}))
    inst.source_documents = list(data.get("source_documents", []))
    inst.active_orders = list(data.get("active_orders", []))
    inst.pending_labs = list(data.get("pending_labs", []))
    inst.mobility_isolation = dict(data.get("mobility_isolation", {}))
    return inst


def load_state(db_path: Path, state_id: str) -> Optional[str]:
    """Return the persisted state JSON for `state_id`, or None when absent/corrupt."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT state_json FROM assembler_state WHERE id = ?", (state_id,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.DatabaseError as exc:
        # Honest degradation: a corrupt state file must never block startup;
        # the caller reseeds the pristine default assembler instead.
        logger.warning("State DB unreadable at %s: %s", db_path, exc)
        return None
    finally:
        conn.close()


def save_state(db_path: Path, state_id: str, state_json: str) -> None:
    """Upsert the state row for `state_id` (atomic, fsync'd by SQLite)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO assembler_state (id, state_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET state_json = excluded.state_json, "
            "updated_at = excluded.updated_at",
            (state_id, state_json, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
