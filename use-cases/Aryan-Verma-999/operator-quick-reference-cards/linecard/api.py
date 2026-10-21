"""FastAPI control plane for the offline, source-locked LineCard demo.

The browser receives only public synthetic evidence and a verified PDF download.
SuperDocs credentials and live provider identifiers never enter these response
models. The live M1 provider discrepancy remains explicitly blocked; this API
does not simulate approval or export from that provider path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any
import uuid

import fitz
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ingest import ingest_pdf
from .layout import pdf_postflight
from .m1 import MANUAL, card_plan, evidence_pack, skeleton, verify
from .retrieval import EvidenceIndex
from .storage import Store

ROOT = Path(__file__).parents[1]
SCALE_MANUAL = ROOT / "fixtures" / "generated" / "scale-manual-400-pages.pdf"
FRONTEND_DIST = ROOT / "frontend" / "dist"
LIVE_LIMITATION = (
    "The live M1 provider proposal-to-chunk contract is blocked: proposal chunk IDs "
    "did not map to synchronized card chunks. No provider approval or export was simulated."
)
HERO_TASK = "Clear a jam on the infeed"


class CardRequest(BaseModel):
    task: str = Field(min_length=1, max_length=240)
    manual_id: str = Field(min_length=1, max_length=240)
    idempotency_key: str | None = Field(default=None, max_length=240)


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, max_length=240)


class EvidenceDecision(BaseModel):
    included: bool


@dataclass
class DemoState:
    task: str = HERO_TASK
    included: set[str] = field(default_factory=set)
    verification: dict[str, Any] | None = None
    exported_pdf: bytes | None = None

    def __post_init__(self) -> None:
        if not self.included:
            self.included = {record["evidence_id"] for record in evidence_pack()["records"]}

    def records(self) -> list[dict[str, Any]]:
        records = []
        for record in evidence_pack()["records"]:
            records.append({
                "id": record["evidence_id"],
                "page": f"PDF p. {record['display_page']}",
                "printed_page": str(record["display_page"]),
                "kind": record["kind"],
                "quote": record["exact_quote"],
                "bbox": record["bbox"],
                "reason": "exact local PDF span",
                "included": record["evidence_id"] in self.included,
            })
        return records

    def card(self) -> dict[str, Any]:
        records = {record["id"]: record for record in self.records()}

        def claim(evidence_id: str) -> dict[str, Any]:
            record = records[evidence_id]
            return {
                "evidence_id": evidence_id,
                "text": record["quote"] if record["included"] else "Evidence excluded — restore this source span before release.",
                "page": record["page"],
                "included": record["included"],
                "kind": record["kind"],
            }

        source_index = [claim(evidence_id) for evidence_id in ("SAFE-001", "STEP-001", "STEP-002", "STEP-003", "SPEC-001", "RESTART-001")]
        return {
            "machine": "LC-100 Synthetic Infeed",
            "task": self.task,
            "complete": all(item["included"] for item in records.values()),
            "missing_evidence_ids": [item["id"] for item in records.values() if not item["included"]],
            "safety": claim("SAFE-001"),
            "tools": claim("STEP-003"),
            "procedure": [claim(evidence_id) for evidence_id in ("STEP-001", "STEP-002", "STEP-003")],
            "specification": claim("SPEC-001"),
            "restart": claim("RESTART-001"),
            "stop": "Stop if energy cannot be isolated, the obstruction cannot be removed with the approved tool, or the interlock fails.",
            "source_index": source_index,
            "disclaimer": "Reviewed job aid subordinate to the OEM manual and site safety procedures. Not a safety certification.",
        }

    def payload(self) -> dict[str, Any]:
        records = self.records()
        return {
            "task": self.task,
            "status": "VERIFIED" if self.verification and self.verification["status"] == "PASS" else "EVIDENCE_READY",
            "evidence": records,
            "included_count": sum(record["included"] for record in records),
            "required_count": len(records),
            "manual_url": "/api/demo/manual",
            "live_limitations": LIVE_LIMITATION,
            "verification": self.verification,
            "card": self.card(),
        }


def _blocked_missing_evidence(state: DemoState) -> dict[str, Any]:
    missing = [record["id"] for record in state.records() if not record["included"]]
    return {
        "status": "BLOCKED",
        "checks": [{
            "check_id": "REQUIRED_EVIDENCE_SELECTION",
            "check": "all required evidence included",
            "passed": False,
            "evidence_ids": missing,
            "expected": "PASS",
            "observed": "BLOCKED",
            "reason": f"required evidence excluded: {', '.join(missing)}",
        }],
    }


def _build_demo_pdf(card: dict[str, Any]) -> bytes:
    """Create the exact reviewed card model served to the browser as a PDF."""
    document = fitz.open()

    def text(page: fitz.Page, value: str, x: float, y: float, *, size: float = 10, bold: bool = False, color: tuple[float, float, float] = (0.13, 0.12, 0.11)) -> float:
        font = "hebo" if bold else "helv"
        height = page.insert_textbox(fitz.Rect(x, y, 540, 748), value, fontsize=size, fontname=font, color=color, lineheight=1.25)
        return y + max(size * 1.55, -height + size * 1.2)

    first = document.new_page(width=612, height=792)
    y = 48.0
    y = text(first, "LINECARD / REVIEWED OPERATOR CARD", 48, y, size=8, bold=True, color=(0.45, 0.42, 0.38))
    y = text(first, card["task"], 48, y + 10, size=24, bold=True)
    y = text(first, f"{card['machine']} · Source-locked review", 48, y + 5, size=10, color=(0.42, 0.39, 0.35))
    safety = card["safety"]
    y = text(first, "SAFETY GATE", 48, y + 28, size=10, bold=True, color=(0.65, 0.22, 0.16))
    y = text(first, f"{safety['text']}  [{safety['evidence_id']} · {safety['page']}]", 48, y + 4, size=12, bold=True)
    y = text(first, "TOOLS / MATERIALS", 48, y + 24, size=10, bold=True)
    tools = card["tools"]
    y = text(first, f"{tools['text']}  [{tools['evidence_id']} · {tools['page']}]", 48, y + 4, size=10)
    y = text(first, "PROCEDURE", 48, y + 22, size=10, bold=True)
    for index, step in enumerate(card["procedure"], start=1):
        y = text(first, f"{index:02d}  {step['text']}  [{step['evidence_id']} · {step['page']}]", 48, y + 4, size=10)
    first.insert_text((500, 760), "01 / 02", fontsize=8, fontname="hebo", color=(0.45, 0.42, 0.38))

    second = document.new_page(width=612, height=792)
    y = 48.0
    y = text(second, "LINECARD / RETURN TO SERVICE", 48, y, size=8, bold=True, color=(0.45, 0.42, 0.38))
    y = text(second, "Restart and verify", 48, y + 10, size=24, bold=True)
    specification = card["specification"]
    y = text(second, "EXACT SPECIFICATION", 48, y + 28, size=10, bold=True)
    y = text(second, f"{specification['text']}  [{specification['evidence_id']} · {specification['page']}]", 48, y + 4, size=13, bold=True)
    restart = card["restart"]
    y = text(second, "RESTART CHECK", 48, y + 24, size=10, bold=True)
    y = text(second, f"{restart['text']}  [{restart['evidence_id']} · {restart['page']}]", 48, y + 4, size=11)
    y = text(second, "STOP / ESCALATE", 48, y + 24, size=10, bold=True)
    y = text(second, card["stop"], 48, y + 4, size=10)
    y = text(second, "SOURCE INDEX", 48, y + 24, size=10, bold=True)
    for item in card["source_index"]:
        y = text(second, f"{item['evidence_id']}  {item['page']}", 48, y + 3, size=9)
    text(second, card["disclaimer"], 48, 714, size=8, color=(0.45, 0.42, 0.38))
    second.insert_text((500, 760), "02 / 02", fontsize=8, fontname="hebo", color=(0.45, 0.42, 0.38))
    return document.tobytes(garbage=4, deflate=True)


def _pdf_postflight(pdf: bytes) -> dict[str, Any]:
    document = fitz.open(stream=pdf, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    return pdf_postflight(page_count=len(document), text=text, warnings=[])


def _scale_check() -> dict[str, Any]:
    """Exercise the real local ingest and retrieval path against 400 pages.

    This is intentionally a scale proof, not a card-generation shortcut. A
    successful check never changes the reviewed four-page hero card or makes a
    new card exportable without its own source-lock review.
    """
    if not SCALE_MANUAL.is_file():
        raise HTTPException(500, "400-page scale manual fixture is missing")

    started = perf_counter()
    manifest = ingest_pdf(SCALE_MANUAL)
    ingest_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    index = EvidenceIndex()
    index.add_manifest(manifest)
    index_ms = (perf_counter() - started) * 1000

    started = perf_counter()
    hits = index.search(HERO_TASK)
    retrieval_ms = (perf_counter() - started) * 1000
    return {
        "fixture": "LC-100 400-page synthetic manual",
        "page_count": manifest["page_count"],
        "byte_size": manifest["byte_size"],
        "sha256": manifest["sha256"],
        "ingest_ms": round(ingest_ms, 2),
        "index_ms": round(index_ms, 2),
        "retrieval_ms": round(retrieval_ms, 2),
        "retrieval_hits": len(hits),
        "matched_pages": [hit.page_index + 1 for hit in hits[:5]],
        "manual_url": "/api/demo/scale/manual",
        "card_eligibility": "BLOCKED_SCALE_PROOF_ONLY",
    }


def create_app(*, store: Store | None = None, state: DemoState | None = None) -> FastAPI:
    app = FastAPI(title="LineCard", version="0.2.0")
    app.state.store = store or Store()
    app.state.demo = state or DemoState()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/demo")
    async def get_demo() -> dict[str, Any]:
        return app.state.demo.payload()

    @app.post("/api/demo/retrieve")
    async def retrieve_demo(request: TaskRequest) -> dict[str, Any]:
        requested = " ".join(request.task.split())
        if requested.casefold() != HERO_TASK.casefold():
            raise HTTPException(422, f"the public demo supports only: {HERO_TASK}")
        app.state.demo.task = HERO_TASK
        app.state.demo.verification = None
        app.state.demo.exported_pdf = None
        return app.state.demo.payload()

    @app.post("/api/demo/scale")
    async def run_scale_check() -> dict[str, Any]:
        return _scale_check()

    @app.post("/api/demo/evidence/{evidence_id}")
    async def decide_demo_evidence(evidence_id: str, decision: EvidenceDecision) -> dict[str, Any]:
        ids = {record["id"] for record in app.state.demo.records()}
        if evidence_id not in ids:
            raise HTTPException(404, "evidence not found")
        if decision.included:
            app.state.demo.included.add(evidence_id)
        else:
            app.state.demo.included.discard(evidence_id)
        app.state.demo.verification = None
        app.state.demo.exported_pdf = None
        return app.state.demo.payload()

    @app.get("/api/demo/evidence/{evidence_id}/preview")
    async def preview_demo_evidence(evidence_id: str) -> Response:
        record = next((item for item in evidence_pack()["records"] if item["evidence_id"] == evidence_id), None)
        if record is None:
            raise HTTPException(404, "evidence not found")
        document = fitz.open(stream=MANUAL.read_bytes(), filetype="pdf")
        page = document[record["page_index"]]
        x0, y0, x1, y1 = record["bbox"]
        highlight = fitz.Rect(x0 - 4, y0 - 3, x1 + 4, y1 + 3)
        page.draw_rect(highlight, color=(0.85, 0.29, 0.22), fill=(1, 0.78, 0.72), fill_opacity=0.45, width=1.2, overlay=True)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
        return Response(pixmap.tobytes("png"), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/demo/verify")
    async def verify_demo() -> dict[str, Any]:
        demo = app.state.demo
        if len(demo.included) != len(demo.records()):
            demo.verification = _blocked_missing_evidence(demo)
        else:
            evidence = evidence_pack()
            demo.verification = verify(skeleton(card_plan(evidence), evidence), evidence)
        return demo.payload()

    @app.post("/api/demo/export")
    async def export_demo() -> dict[str, Any]:
        demo = app.state.demo
        if not demo.verification or demo.verification["status"] != "PASS":
            raise HTTPException(409, "export is disabled until source-lock verification passes")
        pdf = _build_demo_pdf(demo.card())
        postflight = _pdf_postflight(pdf)
        if postflight["status"] != "PASS":
            raise HTTPException(409, "verified demo PDF failed postflight")
        demo.exported_pdf = pdf
        return {
            "status": "READY",
            "download_url": "/api/demo/download",
            "postflight": postflight,
            "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            "page_count": len(fitz.open(stream=pdf, filetype="pdf")),
            "included_evidence_ids": sorted(demo.included),
        }

    @app.get("/api/demo/download")
    async def download_demo() -> Response:
        demo = app.state.demo
        if not demo.verification or demo.verification["status"] != "PASS" or not demo.exported_pdf:
            raise HTTPException(409, "export is disabled until source-lock verification passes")
        return Response(
            demo.exported_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="linecard-reviewed-card.pdf"'},
        )

    @app.get("/api/demo/manual")
    async def download_manual() -> Response:
        return Response(
            MANUAL.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="linecard-synthetic-manual.pdf"'},
        )

    @app.get("/api/demo/scale/manual")
    async def download_scale_manual() -> Response:
        if not SCALE_MANUAL.is_file():
            raise HTTPException(500, "400-page scale manual fixture is missing")
        return Response(
            SCALE_MANUAL.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="linecard-scale-manual-400-pages.pdf"'},
        )

    # A small durable-card API for integration consumers, kept separate from
    # the public demo state above and guarded by idempotency.
    @app.post("/api/cards")
    async def create_card(request: CardRequest) -> dict[str, Any]:
        card_id = "lc_" + uuid.uuid4().hex
        result = {"card_id": card_id, "task": request.task, "manual_id": request.manual_id, "state": "QUEUED"}
        if request.idempotency_key:
            return app.state.store.idempotent(request.idempotency_key, request.model_dump(), result)
        app.state.store.create_job(card_id, result)
        return result

    @app.get("/api/cards/{card_id}")
    async def get_card(card_id: str) -> dict[str, Any]:
        item = app.state.store.get_job(card_id)
        if not item:
            raise HTTPException(404, "card not found")
        return item

    @app.get("/api/cards/{card_id}/proposals")
    async def proposals(card_id: str) -> dict[str, Any]:
        item = app.state.store.get_job(card_id)
        if not item:
            raise HTTPException(404, "card not found")
        return {"card_id": card_id, "proposals": item.get("payload", "{}")}

    @app.post("/api/cards/{card_id}/decisions")
    async def decisions(card_id: str, request: dict[str, Any]) -> dict[str, Any]:
        item = app.state.store.get_job(card_id)
        if not item:
            raise HTTPException(404, "card not found")
        if not isinstance(request.get("decisions"), list) or not request["decisions"]:
            raise HTTPException(422, "decisions must be a non-empty list")
        revision = app.state.store.transition(card_id, item["revision"], "AWAITING_REVIEW", event="decisions", payload=request)
        return {"card_id": card_id, "revision": revision, "status": "AWAITING_REVIEW"}

    @app.post("/api/cards/{card_id}/export")
    async def export_card(card_id: str) -> dict[str, Any]:
        item = app.state.store.get_job(card_id)
        if not item:
            raise HTTPException(404, "card not found")
        if item["state"] != "COMPLETED":
            raise HTTPException(409, "card is not verified")
        return {"card_id": card_id, "status": "EXPORTED"}

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()
