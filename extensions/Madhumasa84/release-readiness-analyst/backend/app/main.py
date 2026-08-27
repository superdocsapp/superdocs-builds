from __future__ import annotations

import json
import tempfile
from collections.abc import Generator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, get_db, init_db
from .models import Finding, ProvenanceEvent, ReportRevision, Run, Source, StageMetric
from .schemas import DecisionBatch, MCPRequest, RunCreate
from .workflow import DecisionError, DurableWorkflow, InjectedInterruption, WorkflowBusy


def create_app() -> FastAPI:
    app = FastAPI(title="Release Readiness Analyst", version="0.1.0")
    workflow = DurableWorkflow(SessionLocal)

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "database": "postgresql+pgvector" if settings.database_url.startswith("postgres") else "sqlite-offline", "workflow": "durable-staged"}

    @app.get("/ready")
    def ready() -> dict:
        try:
            init_db()
            return {"ready": True}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc

    @app.post("/runs", status_code=201)
    def create_run(request: RunCreate) -> dict:
        run = workflow.create_run(request.workspace_id, request.title)
        return {"id": run.id, "workspace_id": run.workspace_id, "title": run.title, "status": run.status}

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        db = SessionLocal()
        try:
            try:
                return workflow.snapshot(db, run_id)
            except AttributeError as exc:
                raise HTTPException(status_code=404, detail="unknown run") from exc
        finally:
            db.close()

    @app.post("/runs/{run_id}/sources", status_code=201)
    async def upload_source(run_id: str, file: UploadFile = File(...)) -> dict:
        total = 0
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as spool:
            while True:
                part = await file.read(64 * 1024)
                if not part:
                    break
                total += len(part)
                if total > settings.max_source_bytes:
                    raise HTTPException(status_code=413, detail="source exceeds configured byte limit")
                spool.write(part)
            spool.seek(0)
            data = spool.read()
        try:
            source = workflow.add_source(run_id, file.filename or "source.txt", file.content_type or "text/plain", data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"id": source.id, "filename": source.filename, "sha256": source.content_sha256, "bytes": source.byte_count, "metadata": source.metadata_json}

    @app.get("/runs/{run_id}/sources")
    def list_sources(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
        return [{"id": source.id, "filename": source.filename, "sha256": source.content_sha256, "bytes": source.byte_count, "metadata": source.metadata_json} for source in db.scalars(select(Source).where(Source.run_id == run_id)).all()]

    @app.post("/runs/{run_id}/execute")
    def execute_run(run_id: str, fail_after_stage: str | None = None) -> dict:
        try:
            return workflow.execute(run_id, fail_after_stage=fail_after_stage)
        except InjectedInterruption as exc:
            return JSONResponse(status_code=503, content={"status": "resumable", "run_id": run_id, "detail": str(exc)})
        except WorkflowBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/resume")
    def resume_run(run_id: str) -> dict:
        try:
            return workflow.resume(run_id)
        except WorkflowBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/findings")
    def list_findings(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
        findings = db.scalars(select(Finding).where(Finding.run_id == run_id)).all()
        return [{"id": f.id, "kind": f.kind, "severity": f.severity, "title": f.title, "summary": f.summary, "citations": f.citations_json, "decision_required": f.decision_required} for f in findings]

    @app.post("/runs/{run_id}/decisions")
    def submit_decisions(run_id: str, batch: DecisionBatch) -> dict:
        try:
            return workflow.submit_decisions(run_id, [item.model_dump() for item in batch.decisions])
        except DecisionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/report")
    def get_report(run_id: str, db: Session = Depends(get_db)) -> dict:
        report = db.scalars(select(ReportRevision).where(ReportRevision.run_id == run_id).order_by(ReportRevision.revision.desc())).first()
        if report is None:
            raise HTTPException(status_code=404, detail="report not available")
        return {"revision": report.revision, "report": report.report_json, "changed_finding_ids": report.changed_finding_ids}

    @app.get("/runs/{run_id}/events")
    def get_events(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
        return [{"type": event.event_type, "actor": event.actor, "payload": event.payload_json, "created_at": event.created_at.isoformat()} for event in db.scalars(select(ProvenanceEvent).where(ProvenanceEvent.run_id == run_id).order_by(ProvenanceEvent.created_at)).all()]

    @app.get("/runs/{run_id}/metrics")
    def get_metrics(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
        return [{"stage": item.stage, "status": item.status, "duration_ms": item.duration_ms, "input_tokens": item.input_tokens, "output_tokens": item.output_tokens, "estimated_cost_usd": item.estimated_cost_usd, "detail": item.detail_json} for item in db.scalars(select(StageMetric).where(StageMetric.run_id == run_id)).all()]

    @app.post("/mcp")
    def mcp(request: MCPRequest) -> dict:
        """Small, schema-validated MCP-compatible machine boundary.

        The production deployment can expose these same operations through an MCP
        transport; keeping the operation vocabulary here makes the machine contract
        testable without a network or credentials.
        """
        if request.operation == "get_run":
            return {"operation": request.operation, "result": get_run(request.run_id)}
        if request.operation == "list_findings":
            db = SessionLocal()
            try:
                return {"operation": request.operation, "result": list_findings(request.run_id, db)}
            finally:
                db.close()
        if request.operation == "get_report":
            db = SessionLocal()
            try:
                return {"operation": request.operation, "result": get_report(request.run_id, db)}
            finally:
                db.close()
        if request.operation == "resume_run":
            return {"operation": request.operation, "result": resume_run(request.run_id)}
        if request.operation == "submit_decisions":
            batch = DecisionBatch.model_validate(request.payload)
            return {"operation": request.operation, "result": submit_decisions(request.run_id, batch)}
        raise HTTPException(status_code=400, detail="unsupported MCP operation")

    return app


app = create_app()
