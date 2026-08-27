from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .config import settings
from .ingestion import chunk_text
from .models import Chunk, Decision, Finding, ProvenanceEvent, ReportRevision, Run, Source, StageMetric, Workspace


STAGES = (
    "parse_sources",
    "extract_requirements",
    "map_evidence",
    "analyze_contradictions",
    "evaluate_release_rules",
    "draft_report",
)


class WorkflowBusy(RuntimeError):
    pass


class InjectedInterruption(RuntimeError):
    pass


class DecisionError(ValueError):
    pass


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(run_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def _pseudo_embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [round((digest[index % len(digest)] / 255.0) * 2 - 1, 6) for index in range(settings.embedding_dimensions)]


def _event(db: Session, run_id: str, event_type: str, payload: dict, actor: str = "workflow") -> None:
    db.add(ProvenanceEvent(id=_id("evt"), run_id=run_id, event_type=event_type, actor=actor, payload_json=payload))


def _citation(source: Source, line: int, quote: str) -> dict:
    return {
        "source_id": source.id,
        "filename": source.filename,
        "sha256": source.content_sha256,
        "locator": {"line_start": line, "line_end": line},
        "quote": quote[:280],
        "verified": True,
    }


class DurableWorkflow:
    """A persisted staged graph; the interface is intentionally LangGraph-compatible."""

    def __init__(self, db_factory: Callable[[], Session]):
        self.db_factory = db_factory

    @contextmanager
    def _lease(self, db: Session, run: Run):
        lock = _lock_for(run.id)
        if not lock.acquire(blocking=False):
            raise WorkflowBusy(f"run {run.id} is already active")
        advisory = False
        try:
            lease_expires = run.lease_expires_at
            if lease_expires is not None and lease_expires.tzinfo is None:
                lease_expires = lease_expires.replace(tzinfo=timezone.utc)
            if lease_expires and lease_expires > datetime.now(timezone.utc) and run.lease_owner:
                raise WorkflowBusy(f"run {run.id} has an active worker lease")
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                advisory = bool(db.scalar(text("SELECT pg_try_advisory_lock(hashtext(:run_id))"), {"run_id": run.id}))
                if not advisory:
                    raise WorkflowBusy(f"run {run.id} is locked by another worker")
            run.lease_owner = f"worker-{uuid.uuid4().hex[:8]}"
            run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
            yield
        finally:
            run.lease_owner = None
            run.lease_expires_at = None
            db.commit()
            if advisory:
                db.execute(text("SELECT pg_advisory_unlock(hashtext(:run_id))"), {"run_id": run.id})
            lock.release()

    def create_run(self, workspace_id: str, title: str) -> Run:
        db = self.db_factory()
        try:
            workspace = db.get(Workspace, workspace_id)
            if workspace is None:
                workspace = Workspace(id=workspace_id, name=workspace_id)
                db.add(workspace)
            run = Run(id=_id("run"), workspace_id=workspace_id, title=title)
            db.add(run)
            _event(db, run.id, "run_created", {"workspace_id": workspace_id, "title": title}, actor="api")
            db.commit()
            return run
        finally:
            db.close()

    def add_source(self, run_id: str, filename: str, media_type: str, data: bytes) -> Source:
        from .ingestion import SourcePayload, extract_text, source_metadata

        if len(data) > settings.max_source_bytes:
            raise ValueError(f"source exceeds {settings.max_source_bytes} bytes")
        payload = SourcePayload(filename=filename, media_type=media_type, data=data)
        text = extract_text(payload)
        metadata = source_metadata(payload, text)
        db = self.db_factory()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise ValueError("unknown run")
            digest = metadata["sha256"]
            existing = db.scalar(select(Source).where(Source.run_id == run_id, Source.content_sha256 == digest))
            if existing:
                return existing
            source = Source(
                id=_id("src"),
                run_id=run_id,
                filename=filename,
                media_type=media_type or "text/plain",
                content_sha256=digest,
                byte_count=len(data),
                content_text=text,
                metadata_json=metadata,
            )
            db.add(source)
            # A new source invalidates downstream graph checkpoints. Existing
            # source chunks remain immutable and are reused by parse_sources.
            run.state_json = {**run.state_json, "completed_stages": []}
            run.status = "created"
            run.current_stage = "created"
            _event(db, run_id, "source_ingested", {"source_id": source.id, "filename": filename, "sha256": digest})
            db.commit()
            return source
        finally:
            db.close()

    def execute(self, run_id: str, fail_after_stage: str | None = None, resume: bool = False) -> dict:
        db = self.db_factory()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise ValueError("unknown run")
            with self._lease(db, run):
                run.status = "running"
                run.failure_message = None
                db.commit()
                completed = set(run.state_json.get("completed_stages", []))
                for stage in STAGES:
                    if stage in completed:
                        continue
                    self._run_stage(db, run, stage)
                    completed.add(stage)
                    run.state_json = {**run.state_json, "completed_stages": sorted(completed)}
                    run.state_version += 1
                    db.commit()
                    if fail_after_stage == stage:
                        run.status = "resumable"
                        run.failure_message = "interrupted by deterministic failure injection"
                        db.commit()
                        raise InjectedInterruption(run.failure_message)
                required = db.scalars(select(Finding).where(Finding.run_id == run_id, Finding.decision_required.is_(True))).all()
                decisions = {d.finding_id: d for d in db.scalars(select(Decision).where(Decision.run_id == run_id)).all()}
                run.status = "awaiting_decisions" if any(f.id not in decisions for f in required) else "completed"
                run.current_stage = "completed"
                _event(db, run_id, "run_waiting_for_decisions" if run.status == "awaiting_decisions" else "run_completed", {"required": len(required)})
                db.commit()
                return self.snapshot(db, run_id)
        except InjectedInterruption:
            raise
        except WorkflowBusy:
            raise
        except Exception as exc:
            db.rollback()
            run = db.get(Run, run_id)
            if run:
                run.status = "failed"
                run.failure_message = str(exc)[:1000]
                db.commit()
            raise
        finally:
            db.close()

    def resume(self, run_id: str) -> dict:
        db = self.db_factory()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise ValueError("unknown run")
            if run.status == "completed":
                return self.snapshot(db, run_id)
            if run.status == "awaiting_decisions":
                return self.snapshot(db, run_id)
        finally:
            db.close()
        return self.execute(run_id, resume=True)

    def submit_decisions(self, run_id: str, decisions: list[dict]) -> dict:
        db = self.db_factory()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise DecisionError("unknown run")
            findings = db.scalars(select(Finding).where(Finding.run_id == run_id, Finding.decision_required.is_(True))).all()
            known = {finding.id for finding in findings}
            supplied: set[str] = set()
            for item in decisions:
                finding_id = item["finding_id"]
                if finding_id not in known:
                    raise DecisionError(f"unknown finding_id: {finding_id}")
                if finding_id in supplied:
                    raise DecisionError(f"duplicate finding_id: {finding_id}")
                supplied.add(finding_id)
                existing = db.scalar(select(Decision).where(Decision.run_id == run_id, Decision.finding_id == finding_id))
                if existing:
                    existing.state = item["state"]
                    existing.feedback = item.get("feedback")
                else:
                    db.add(Decision(id=_id("dec"), run_id=run_id, finding_id=finding_id, state=item["state"], feedback=item.get("feedback"), reviewer=item.get("reviewer", "local-reviewer")))
                _event(db, run_id, "decision_submitted", {"finding_id": finding_id, "state": item["state"]}, actor=item.get("reviewer", "local-reviewer"))
            db.flush()
            current = {d.finding_id for d in db.scalars(select(Decision).where(Decision.run_id == run_id)).all()}
            missing = sorted(known - current)
            if missing:
                run.status = "awaiting_decisions"
            else:
                run.status = "completed"
                run.current_stage = "completed"
            db.commit()
            return {**self.snapshot(db, run_id), "missing_decisions": missing}
        finally:
            db.close()

    def _run_stage(self, db: Session, run: Run, stage: str) -> None:
        started = time.perf_counter()
        run.current_stage = stage
        db.commit()
        detail: dict = {}
        if stage == "parse_sources":
            sources = db.scalars(select(Source).where(Source.run_id == run.id)).all()
            for source in sources:
                existing = db.scalars(select(Chunk).where(Chunk.source_id == source.id)).all()
                if existing:
                    continue
                for ordinal, (text, start, end) in enumerate(chunk_text(source.content_text)):
                    db.add(Chunk(id=_id("chk"), source_id=source.id, ordinal=ordinal, text=text, start_line=start, end_line=end, embedding_json=_pseudo_embedding(text), embedding_vector=_pseudo_embedding(text)))
            detail = {"sources": len(sources)}
        elif stage == "extract_requirements":
            requirements = []
            for source in db.scalars(select(Source).where(Source.run_id == run.id)).all():
                for line_number, line in enumerate(source.content_text.splitlines(), start=1):
                    if re.match(r"^(?:REQ-[A-Z0-9_-]+|\[REQ\])\s+(?!status\s*:)", line.strip(), flags=re.IGNORECASE):
                        requirements.append({"source_id": source.id, "line": line_number, "text": line.strip()})
            run.state_json = {**run.state_json, "requirements": requirements}
            detail = {"requirements": len(requirements)}
        elif stage in ("map_evidence", "analyze_contradictions"):
            self._upsert_findings(db, run)
            detail = {"findings": len(db.scalars(select(Finding).where(Finding.run_id == run.id)).all())}
        elif stage == "evaluate_release_rules":
            findings = db.scalars(select(Finding).where(Finding.run_id == run.id)).all()
            blockers = sum(1 for finding in findings if finding.severity == "critical")
            run.state_json = {**run.state_json, "rule_result": "blocked" if blockers else "conditional", "critical_blockers": blockers}
            detail = {"critical_blockers": blockers}
        elif stage == "draft_report":
            self._write_report(db, run)
            detail = {"revision": len(db.scalars(select(ReportRevision).where(ReportRevision.run_id == run.id)).all())}
        duration_ms = max(1, int((time.perf_counter() - started) * 1000))
        db.add(StageMetric(id=_id("met"), run_id=run.id, stage=stage, status="completed", duration_ms=duration_ms, input_tokens=sum(len(s.content_text.split()) for s in db.scalars(select(Source).where(Source.run_id == run.id)).all()), output_tokens=len(json.dumps(detail)), estimated_cost_usd=0.0, detail_json=detail))
        _event(db, run.id, "stage_completed", {"stage": stage, "duration_ms": duration_ms, **detail})

    def _upsert_findings(self, db: Session, run: Run) -> None:
        sources = db.scalars(select(Source).where(Source.run_id == run.id)).all()
        requirements = run.state_json.get("requirements", [])
        desired: list[dict] = []
        for source in sources:
            hits = source.metadata_json.get("prompt_injection_hits", [])
            if hits:
                desired.append({"key": f"prompt:{source.id}", "kind": "security", "severity": "critical", "title": "Instruction-like content in source", "summary": "The source contains text that resembles an instruction to the analyst. It was treated as untrusted evidence and not executed.", "citations": [_citation(source, 1, source.content_text)]})
        for req in requirements:
            source = next((item for item in sources if item.id == req["source_id"]), None)
            if source is None:
                continue
            req_key = req["text"].split()[0]
            evidence_lines = []
            for candidate in sources:
                for number, line in enumerate(candidate.content_text.splitlines(), start=1):
                    if req_key.lower() in line.lower() and line.strip() != req["text"]:
                        evidence_lines.append((candidate, number, line.strip()))
            if not evidence_lines:
                desired.append({"key": f"missing:{req_key}", "kind": "missing_evidence", "severity": "critical", "title": f"Missing evidence for {req_key}", "summary": "No supporting evidence was found for this requirement.", "citations": [_citation(source, req["line"], req["text"])]})
            else:
                pass_lines = [entry for entry in evidence_lines if "pass" in entry[2].lower() or "verified" in entry[2].lower()]
                fail_lines = [entry for entry in evidence_lines if "fail" in entry[2].lower() or "broken" in entry[2].lower()]
                if pass_lines and fail_lines:
                    desired.append({"key": f"contradiction:{req_key}", "kind": "contradiction", "severity": "critical", "title": f"Contradictory evidence for {req_key}", "summary": "Evidence contains both positive and negative outcomes; a reviewer must decide which source is authoritative.", "citations": [_citation(*pass_lines[0]), _citation(*fail_lines[0])]})
                else:
                    desired.append({"key": f"covered:{req_key}", "kind": "coverage", "severity": "info", "title": f"Evidence found for {req_key}", "summary": "Supporting evidence was located and linked to this requirement.", "citations": [_citation(*evidence_lines[0])]})
        existing = {finding.metadata_json.get("key"): finding for finding in db.scalars(select(Finding).where(Finding.run_id == run.id)).all()}
        for item in desired:
            finding_id = existing.get(item["key"], Finding(id=_id("fnd"), run_id=run.id, kind=item["kind"], severity=item["severity"], title=item["title"], summary=item["summary"], metadata_json={"key": item["key"]})).id
            finding = existing.get(item["key"])
            if finding is None:
                finding = Finding(id=finding_id, run_id=run.id, kind=item["kind"], severity=item["severity"], title=item["title"], summary=item["summary"], citations_json=item["citations"], metadata_json={"key": item["key"]}, decision_required=item["severity"] != "info")
                db.add(finding)
            else:
                finding.citations_json = item["citations"]
                finding.summary = item["summary"]

    def _write_report(self, db: Session, run: Run) -> None:
        findings = db.scalars(select(Finding).where(Finding.run_id == run.id)).all()
        decisions = {item.finding_id: item.state for item in db.scalars(select(Decision).where(Decision.run_id == run.id)).all()}
        prior = db.scalars(select(ReportRevision).where(ReportRevision.run_id == run.id).order_by(ReportRevision.revision.desc())).first()
        report = {"schema_version": "1.0", "run_id": run.id, "title": run.title, "verdict": run.state_json.get("rule_result", "pending"), "findings": [{"id": finding.id, "kind": finding.kind, "severity": finding.severity, "title": finding.title, "summary": finding.summary, "citations": finding.citations_json, "decision": decisions.get(finding.id, "pending")} for finding in findings], "provenance": {"source_count": len(db.scalars(select(Source).where(Source.run_id == run.id)).all()), "generated_by": "deterministic-release-readiness-v1"}}
        previous_findings = {item["id"]: item for item in (prior.report_json.get("findings", []) if prior else [])}
        changed = [item["id"] for item in report["findings"] if previous_findings.get(item["id"]) != item]
        db.add(ReportRevision(id=_id("rpt"), run_id=run.id, revision=(prior.revision + 1 if prior else 1), report_json=report, changed_finding_ids=changed))
        run.state_json = {**run.state_json, "last_report_changed_finding_ids": changed}

    def snapshot(self, db: Session, run_id: str) -> dict:
        run = db.get(Run, run_id)
        findings = db.scalars(select(Finding).where(Finding.run_id == run_id)).all()
        latest = db.scalars(select(ReportRevision).where(ReportRevision.run_id == run_id).order_by(ReportRevision.revision.desc())).first()
        metrics = db.scalars(select(StageMetric).where(StageMetric.run_id == run_id).order_by(StageMetric.id)).all()
        return {"id": run.id, "workspace_id": run.workspace_id, "title": run.title, "status": run.status, "current_stage": run.current_stage, "state_version": run.state_version, "failure_message": run.failure_message, "findings": [{"id": f.id, "kind": f.kind, "severity": f.severity, "title": f.title, "summary": f.summary, "citations": f.citations_json, "decision_required": f.decision_required} for f in findings], "report": latest.report_json if latest else None, "metrics": [{"stage": m.stage, "status": m.status, "duration_ms": m.duration_ms, "input_tokens": m.input_tokens, "output_tokens": m.output_tokens, "estimated_cost_usd": m.estimated_cost_usd} for m in metrics]}
