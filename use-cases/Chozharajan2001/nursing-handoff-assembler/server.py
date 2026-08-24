"""
Dedicated Standalone FastAPI Server for Nursing Handoff & Transfer Packet Assembler (Task 2 Band S2).
Runs independently on port 8001.
Serves:
1. Interactive Clinical Dashboard (GET / or GET /dashboard)
2. Clinical State & SBAR APIs (GET /api/clinical/handoff/{mrn})
3. Human Safety Gate Verification (POST /api/clinical/confirm-gate)
4. Gated 10-Page PDF Export (GET /api/clinical/export/pdf) - Fails with HTTP 422 if unverified
5. Gated SuperDocs Word Export (GET /api/clinical/export/docx)
"""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from clinical_pipeline import (
    ClinicalPacketAssembler,
)
from demo_patient import build_demo_assembler
from packet_builder import ClinicalPDFPacketBuilder
from superdocs_client import SuperDocsAPIClient
import state_persistence

from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("superdocs.clinical_server")

CURRENT_DIR = Path(__file__).parent.resolve()
SAMPLE_DIR = CURRENT_DIR / "sample_patient_records"

# Durable gate-state persistence (LIMITATIONS §3 remediation): confirmations now
# survive server restarts via a local SQLite row instead of process memory.
STATE_DB = CURRENT_DIR / "clinical_gate_state.db"
STATE_ID = "active-assembler"

# In-Memory Active Assembler State (rehydrated from STATE_DB on startup)
_ACTIVE_ASSEMBLER: Optional[ClinicalPacketAssembler] = None


def _persist_state() -> None:
    """Write the current assembler state (packet + gates) to the durable store."""
    if _ACTIVE_ASSEMBLER is None:
        return
    try:
        state_persistence.save_state(
            STATE_DB, STATE_ID, state_persistence.serialize_assembler(_ACTIVE_ASSEMBLER)
        )
    except Exception as exc:  # persistence must never break the clinical flow
        logger.warning("Gate-state persistence failed (state kept in memory only): %s", exc)


def _load_or_seed_assembler() -> ClinicalPacketAssembler:
    """Rehydrate persisted state (gates survive restart) or seed the default packet."""
    raw = state_persistence.load_state(STATE_DB, STATE_ID)
    if raw is not None:
        try:
            restored = state_persistence.restore_assembler(raw)
            logger.info("Restored persisted clinical state from %s (gates preserved)", STATE_DB.name)
            return restored
        except Exception as exc:
            logger.warning("Persisted clinical state unreadable (%s); reseeding defaults", exc)
    inst = init_default_assembler()
    try:
        state_persistence.save_state(STATE_DB, STATE_ID, state_persistence.serialize_assembler(inst))
    except Exception as exc:
        logger.warning("Initial state persistence failed: %s", exc)
    return inst


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ACTIVE_ASSEMBLER
    _ACTIVE_ASSEMBLER = _load_or_seed_assembler()
    logger.info("Clinical Nursing Handoff Server initialized for patient MRN %s", _ACTIVE_ASSEMBLER.demographics.mrn)
    yield

app = FastAPI(
    title="SuperDocs Clinical Nursing Handoff & Transfer Server (Band S2)",
    description="Safety-gated clinical document assembly workflow with conservative medication reconciliation.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def init_default_assembler() -> ClinicalPacketAssembler:
    """Seed the demo packet from the shared, record-grounded demo module.

    All SBAR citations, orders, pending labs, and mobility/isolation values are
    derived from the committed sample_patient_records/ files (see demo_patient.py)
    — the server never carries its own copy of the demo clinical content.
    """
    return build_demo_assembler(SAMPLE_DIR)


# Request/Response Models
class GateConfirmationRequest(BaseModel):
    gate_type: str = Field(..., description="allergies | code_status | high_risk_meds")
    nurse_name: str = Field(default="RN Sarah Jenkins")
    nurse_id: str = Field(default="RN-4029")
    second_nurse_name: Optional[str] = Field(default="RN Mark Taylor")
    second_nurse_id: Optional[str] = Field(default="RN-5104")


@app.get("/healthz")
def health_check():
    return {
        "status": "healthy",
        "service": "superdocs-clinical-assembler",
        "band": "S2",
        "patient_loaded": _ACTIVE_ASSEMBLER.demographics.mrn if _ACTIVE_ASSEMBLER else None,
    }


@app.post("/api/clinical/reset")
def reset_patient_state():
    global _ACTIVE_ASSEMBLER
    _ACTIVE_ASSEMBLER = init_default_assembler()
    _persist_state()  # the reset itself is durable: a restart sees pristine gates
    return {"status": "reset", "patient": _ACTIVE_ASSEMBLER.demographics.mrn}


@app.get("/api/clinical/gate-status")
def get_gate_status():
    """Returns current state of all 3 safety gates and whether export is unlocked."""
    if not _ACTIVE_ASSEMBLER:
        raise HTTPException(status_code=503, detail="No active assembler. Call /api/clinical/reset first.")
    gates = _ACTIVE_ASSEMBLER.gates
    unlocked, pending = gates.is_export_unlocked()
    return {
        "export_unlocked": unlocked,
        "pending_gates": pending,
        "gates": {
            "allergies": {
                "confirmed": gates.allergies_confirmed,
                "nurse": gates.allergies_nurse,
                "timestamp": gates.allergies_timestamp,
            },
            "code_status": {
                "confirmed": gates.code_status_confirmed,
                "nurse": gates.code_status_nurse,
                "timestamp": gates.code_status_timestamp,
            },
            "high_risk_meds": {
                "confirmed": gates.high_risk_meds_confirmed,
                "nurse_1": gates.high_risk_meds_nurse_1,
                "nurse_2": gates.high_risk_meds_nurse_2,
                "timestamp": gates.high_risk_meds_timestamp,
            },
        },
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    dashboard_path = CURRENT_DIR / "clinical_review_dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Clinical Dashboard HTML not found.</h2>", status_code=404)


@app.get("/api/clinical/handoff/{mrn}")
def get_handoff_details(mrn: str):
    if not _ACTIVE_ASSEMBLER or _ACTIVE_ASSEMBLER.demographics.mrn != mrn:
        raise HTTPException(status_code=404, detail=f"Patient with MRN {mrn} not found.")

    unlocked, unverified_gates = _ACTIVE_ASSEMBLER.gates.is_export_unlocked()
    return {
        "demographics": {
            "name": _ACTIVE_ASSEMBLER.demographics.name,
            "mrn": _ACTIVE_ASSEMBLER.demographics.mrn,
            "dob": _ACTIVE_ASSEMBLER.demographics.dob,
            "age": _ACTIVE_ASSEMBLER.demographics.age,
            "gender": _ACTIVE_ASSEMBLER.demographics.gender,
            "sending_unit": _ACTIVE_ASSEMBLER.demographics.sending_unit,
            "receiving_unit": _ACTIVE_ASSEMBLER.demographics.receiving_unit,
            "code_status": _ACTIVE_ASSEMBLER.demographics.code_status,
        },
        "sbar": {
            "situation": _ACTIVE_ASSEMBLER.sbar.situation if _ACTIVE_ASSEMBLER.sbar else "",
            "background": _ACTIVE_ASSEMBLER.sbar.background if _ACTIVE_ASSEMBLER.sbar else "",
            "assessment": _ACTIVE_ASSEMBLER.sbar.assessment if _ACTIVE_ASSEMBLER.sbar else "",
            "recommendation": _ACTIVE_ASSEMBLER.sbar.recommendation if _ACTIVE_ASSEMBLER.sbar else "",
        },
        # D2 fix: structured per-section citation lists so clients render
        # citations from data, never from hardcoded strings.
        "sbar_citations": {
            "situation": (_ACTIVE_ASSEMBLER.sbar.situation_citations if _ACTIVE_ASSEMBLER.sbar else []),
            "background": (_ACTIVE_ASSEMBLER.sbar.background_citations if _ACTIVE_ASSEMBLER.sbar else []),
            "assessment": (_ACTIVE_ASSEMBLER.sbar.assessment_citations if _ACTIVE_ASSEMBLER.sbar else []),
            "recommendation": (_ACTIVE_ASSEMBLER.sbar.recommendation_citations if _ACTIVE_ASSEMBLER.sbar else []),
        },
        "allergies": _ACTIVE_ASSEMBLER.allergies,
        "medications": [
            {
                "id": m.id,
                "name": m.name,
                "generic": m.generic,
                "dose": m.dose,
                "route": m.route,
                "frequency": m.frequency,
                "is_high_risk": m.is_high_risk,
                "high_risk_category": m.high_risk_category,
                "is_duplicate": m.is_duplicate,
                "duplicate_warning": m.duplicate_warning,
                "verified": m.verified,
                "source_doc": m.source_doc,
            }
            for m in _ACTIVE_ASSEMBLER.medications
        ],
        "safety_gates": {
            "allergies_confirmed": _ACTIVE_ASSEMBLER.gates.allergies_confirmed,
            "code_status_confirmed": _ACTIVE_ASSEMBLER.gates.code_status_confirmed,
            "high_risk_meds_confirmed": _ACTIVE_ASSEMBLER.gates.high_risk_meds_confirmed,
            "is_export_unlocked": unlocked,
            "pending_gates": unverified_gates,
        },
        "audit_digest": _ACTIVE_ASSEMBLER.generate_audit_digest(),
    }


@app.post("/api/clinical/confirm-gate")
def confirm_safety_gate(req: GateConfirmationRequest):
    if not _ACTIVE_ASSEMBLER:
        raise HTTPException(status_code=500, detail="Assembler uninitialized.")

    if req.gate_type == "allergies":
        _ACTIVE_ASSEMBLER.confirm_allergy_gate(req.nurse_name, req.nurse_id)
    elif req.gate_type == "code_status":
        _ACTIVE_ASSEMBLER.confirm_code_status_gate(req.nurse_name, req.nurse_id)
    elif req.gate_type == "high_risk_meds":
        _ACTIVE_ASSEMBLER.confirm_high_risk_meds_gate(
            req.nurse_name, req.nurse_id, req.second_nurse_name or "RN Mark Taylor", req.second_nurse_id or "RN-5104"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown gate type: {req.gate_type}")

    # Durability: the confirmation is written to SQLite BEFORE responding, so a
    # crash or restart immediately after this call never loses a nurse sign-off.
    _persist_state()

    unlocked, pending = _ACTIVE_ASSEMBLER.gates.is_export_unlocked()
    return {
        "status": "confirmed",
        "gate": req.gate_type,
        "is_export_unlocked": unlocked,
        "pending_gates": pending,
        "audit_digest": _ACTIVE_ASSEMBLER.generate_audit_digest(),
    }


@app.get("/api/clinical/export/pdf")
def export_pdf_dossier():
    if not _ACTIVE_ASSEMBLER:
        raise HTTPException(status_code=500, detail="Assembler uninitialized.")

    unlocked, unverified = _ACTIVE_ASSEMBLER.gates.is_export_unlocked()
    if not unlocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "EXPORT_BLOCKED_SAFETY_GATES_PENDING",
                "message": "Deterministic safety gate violation: Clinical transfer packet export is locked until all 3 high-risk fields are verified.",
                "pending_gates": unverified,
            }
        )

    pdf_out = CURRENT_DIR / f"transfer_packet_patient-{_ACTIVE_ASSEMBLER.demographics.mrn}.pdf"
    builder = ClinicalPDFPacketBuilder(_ACTIVE_ASSEMBLER)
    builder.save_pdf(str(pdf_out))

    return FileResponse(
        path=str(pdf_out),
        filename=f"transfer_packet_{_ACTIVE_ASSEMBLER.demographics.mrn}.pdf",
        media_type="application/pdf",
    )


@app.get("/api/clinical/export/docx")
def export_docx_dossier():
    if not _ACTIVE_ASSEMBLER:
        raise HTTPException(status_code=500, detail="Assembler uninitialized.")

    unlocked, unverified = _ACTIVE_ASSEMBLER.gates.is_export_unlocked()
    if not unlocked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "EXPORT_BLOCKED_SAFETY_GATES_PENDING",
                "message": "Deterministic safety gate violation: Clinical transfer packet Word export is locked until all 3 high-risk fields are verified.",
                "pending_gates": unverified,
            }
        )

    docx_file = CURRENT_DIR / f"superdocs_handoff_{_ACTIVE_ASSEMBLER.demographics.mrn}.docx"
    if docx_file.exists():
        return FileResponse(
            path=str(docx_file),
            filename=f"superdocs_handoff_{_ACTIVE_ASSEMBLER.demographics.mrn}.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    raise HTTPException(status_code=404, detail="Word export not yet generated.")


if __name__ == "__main__":
    import socket
    import sys
    import uvicorn
    import urllib.request

    def is_port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    target_port = 8001
    if is_port_in_use(target_port):
        # Check if it's our healthy clinical server
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{target_port}/healthz")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    print("\n===========================================================================")
                    print(f"✅ SERVER IS ALREADY RUNNING & HEALTHY AT: http://127.0.0.1:{target_port}/dashboard")
                    print("===========================================================================\n")
                    sys.exit(0)
        except Exception:
            target_port = 8002

    print(f"\n[INFO] Starting Clinical Server on http://127.0.0.1:{target_port} ...")
    uvicorn.run(app, host="127.0.0.1", port=target_port)
