from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from .db import Database, now
from .superdocs import RunResult, SuperDocsClient, SuperDocsError, resolve_pending_changes
from .document_evidence import diff_documents, parse_document_html, render_annotated_document, resolve_changes
from .targeting import PUBLIC_FAILURE_DEFINITIONS, assess_targeting, simplify_failure_category, verdict_summary


class BenchmarkService:
    CURRENT_CORPUS_VERSION = "1.1.0"

    def __init__(self, db: Database, client: SuperDocsClient | None, max_batch_cases: int = 5, max_batch_operations: int = 5):
        self.db, self.client = db, client
        self.max_batch_cases, self.max_batch_operations = max_batch_cases, max_batch_operations

    def current_benchmark_run(self) -> dict[str, Any]:
        row=self.db.one("SELECT * FROM benchmark_runs WHERE selected=1 ORDER BY id DESC LIMIT 1")
        if not row: raise ValueError("no benchmark run is selected")
        return row

    def _ensure_benchmark_run_writable(self, benchmark_run_id: int) -> None:
        row=self.db.one("SELECT read_only FROM benchmark_runs WHERE id=?",(benchmark_run_id,))
        if not row: raise ValueError("benchmark run not found")
        if row.get("read_only"): raise ValueError("published benchmark snapshots are read-only; start a fresh benchmark run to make changes")

    def _ensure_execution_writable(self, run_id: int) -> None:
        row=self.db.one("""SELECT b.read_only FROM runs r JOIN benchmark_runs b ON b.id=r.benchmark_run_id WHERE r.id=?""",(run_id,))
        if not row: raise ValueError("run not found")
        if row.get("read_only"): raise ValueError("published benchmark snapshots are read-only; start a fresh benchmark run to make changes")

    def list_benchmark_runs(self) -> list[dict[str, Any]]:
        return self.db.all("""SELECT b.*,COUNT(r.id) execution_attempts,
          COUNT(DISTINCT CASE WHEN c.external_case_id IS NOT NULL THEN r.case_id END) official_cases_run,
          b.corpus_case_total official_cases_total
          FROM benchmark_runs b LEFT JOIN runs r ON r.benchmark_run_id=b.id
          LEFT JOIN cases c ON c.id=r.case_id GROUP BY b.id ORDER BY b.id DESC""")

    def start_benchmark_run(self) -> dict[str, Any]:
        with self.db.connect() as db:
            number=db.execute("SELECT COUNT(*)+1 FROM benchmark_runs").fetchone()[0]
            db.execute("UPDATE benchmark_runs SET selected=0")
            total=db.execute("SELECT COUNT(*) FROM cases WHERE external_case_id IS NOT NULL").fetchone()[0]
            run_id=db.execute("INSERT INTO benchmark_runs(name,selected,corpus_version,corpus_case_total,created_at) VALUES (?,?,?,?,?)",(f"Benchmark run {number}",1,self.CURRENT_CORPUS_VERSION,total,now())).lastrowid
            db.execute("INSERT INTO benchmark_run_cases(benchmark_run_id,case_id) SELECT ?,id FROM cases WHERE external_case_id IS NOT NULL",(run_id,))
        return self.db.one("SELECT * FROM benchmark_runs WHERE id=?",(run_id,))

    def select_benchmark_run(self, benchmark_run_id: int) -> dict[str, Any]:
        if not self.db.one("SELECT id FROM benchmark_runs WHERE id=?",(benchmark_run_id,)): raise ValueError("benchmark run not found")
        with self.db.connect() as db:
            db.execute("UPDATE benchmark_runs SET selected=0")
            db.execute("UPDATE benchmark_runs SET selected=1 WHERE id=?",(benchmark_run_id,))
        return self.current_benchmark_run()

    def import_corpus(self, manifest_path: str | Path) -> dict[str, Any]:
        path=Path(manifest_path).resolve(); data=json.loads(path.read_text()); document_dir=path.parent/"documents"
        if data.get("document_count")!=14 or data.get("case_count")!=60: raise ValueError("manifest must describe the frozen 14-document / 60-case corpus")
        verified=[]
        for item in data["documents"]:
            file=document_dir/item["filename"]
            if not file.is_file(): raise ValueError(f"fixture missing: {item['filename']}")
            actual=hashlib.sha256(file.read_bytes()).hexdigest()
            if actual!=item["sha256"]: raise ValueError(f"fixture hash mismatch for {item['filename']}: expected {item['sha256']}, got {actual}")
            verified.append((item,file,actual))
        created_docs=created_cases=0
        with self.db.connect() as db:
            doc_ids={}
            for item,file,actual in verified:
                row=db.execute("SELECT id,expected_sha256,actual_sha256 FROM documents WHERE external_document_id=?",(item["document_id"],)).fetchone()
                if row:
                    if row["expected_sha256"]!=item["sha256"] or hashlib.sha256(db.execute("SELECT content FROM documents WHERE id=?",(row["id"],)).fetchone()[0]).hexdigest()!=item["sha256"]: raise ValueError(f"stored frozen fixture mismatch for {item['document_id']}")
                    doc_ids[item["document_id"]]=row["id"]
                else:
                    cur=db.execute("""INSERT INTO documents(name,filename,content_type,content,external_document_id,fixture_version,expected_sha256,actual_sha256,source_path,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",(item["name"],item["filename"],"application/vnd.openxmlformats-officedocument.wordprocessingml.document",file.read_bytes(),item["document_id"],item["fixture_version"],item["sha256"],actual,str(file),now()))
                    doc_ids[item["document_id"]]=cur.lastrowid; created_docs+=1
            for case in data["cases"]:
                existing=db.execute("SELECT id FROM cases WHERE external_case_id=?",(case["case_id"],)).fetchone()
                values=(case["case_id"],case["case_type"],doc_ids[case["document_id"]],case["instruction"],case.get("expected_section_path") or "",case.get("expected_answer"),case["case_id"],case.get("difficulty"),case["expected_behavior"],case.get("expected_section_path"),json.dumps(case.get("acceptable_section_paths") or []),case.get("expected_edit_scope"),json.dumps(case.get("must_not_target") or []),case.get("capability_tested"),case.get("likely_failure_category"),case.get("rationale"),case.get("fixture_version"),case.get("document_sha256"))
                if existing:
                    stored=db.execute("SELECT document_id,fixture_version,expected_document_sha256 FROM cases WHERE id=?",(existing["id"],)).fetchone()
                    if stored["document_id"]!=doc_ids[case["document_id"]] or stored["fixture_version"]!=case["fixture_version"] or stored["expected_document_sha256"]!=case["document_sha256"]: raise ValueError(f"existing case conflicts with frozen manifest: {case['case_id']}")
                    continue
                db.execute("""INSERT INTO cases(title,case_type,document_id,instruction,expected_section,expected_answer,external_case_id,difficulty,expected_behavior,expected_section_path,acceptable_section_paths_json,expected_edit_scope,must_not_target_json,capability_tested,likely_failure_category,rationale,fixture_version,expected_document_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(*values,now())); created_cases+=1
            # A brand-new database creates an empty initial run before import.
            # Populate only such empty runs; historical snapshots stay unchanged.
            for benchmark_run in db.execute("SELECT id FROM benchmark_runs").fetchall():
                run_id=benchmark_run["id"]
                member_count=db.execute("SELECT COUNT(*) FROM benchmark_run_cases WHERE benchmark_run_id=?",(run_id,)).fetchone()[0]
                execution_count=db.execute("SELECT COUNT(*) FROM runs WHERE benchmark_run_id=?",(run_id,)).fetchone()[0]
                if member_count==0 and execution_count==0:
                    db.execute("INSERT INTO benchmark_run_cases(benchmark_run_id,case_id) SELECT ?,id FROM cases WHERE external_case_id IS NOT NULL",(run_id,))
                    db.execute("UPDATE benchmark_runs SET corpus_version=?,corpus_case_total=? WHERE id=?",(data.get("corpus_version") or self.CURRENT_CORPUS_VERSION,data["case_count"],run_id))
        return {"status":"imported","corpus_version":data.get("corpus_version") or self.CURRENT_CORPUS_VERSION,"fixture_version":data["fixture_version"],"documents_created":created_docs,"cases_created":created_cases,"documents_total":14,"cases_total":60}

    def verify_case_integrity(self, case_id: int) -> dict[str, Any]:
        row=self.db.one("""SELECT c.external_case_id,c.expected_document_sha256,d.id document_id,d.filename,d.content,d.expected_sha256 FROM cases c JOIN documents d ON d.id=c.document_id WHERE c.id=?""",(case_id,))
        if not row: raise ValueError("case not found")
        expected=row.get("expected_document_sha256") or row.get("expected_sha256")
        actual=hashlib.sha256(row["content"]).hexdigest()
        if expected and actual!=expected: raise ValueError(f"frozen fixture changed for {row.get('external_case_id') or case_id} ({row['filename']}): expected SHA-256 {expected}, got {actual}; run blocked")
        return {"expected_sha256":expected,"actual_sha256":actual,"verified":not expected or expected==actual}

    def run_case(self, case_id: int, benchmark_run_id: int | None=None) -> dict[str, Any]:
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
        self._ensure_benchmark_run_writable(benchmark_run_id)
        if not self.db.one("SELECT 1 FROM benchmark_run_cases WHERE benchmark_run_id=? AND case_id=?",(benchmark_run_id,case_id)): raise ValueError("case is not part of this benchmark run's corpus")
        self.verify_case_integrity(case_id)
        case=self.db.one("SELECT * FROM cases WHERE id=?",(case_id,)); document=self.db.one("SELECT * FROM documents WHERE id=?",(case["document_id"],)) if case else None
        if not case or not document: raise ValueError("case not found")
        if self.client is None: raise ValueError("SuperDocs client is not configured")
        try: result=self.client.run(self.db.decode_case(case),document)
        except SuperDocsError as exc: result=RunResult("error","",None,{}, {},0,error=str(exc))
        if not self.db.one("SELECT id FROM benchmark_runs WHERE id=?",(benchmark_run_id,)): raise ValueError("benchmark run not found")
        run_id=self.db.execute("""INSERT INTO runs(case_id,benchmark_run_id,status,session_id,job_id,textual_response,evidence_json,raw_response_json,latency_ms,operations_charged,error,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",(case_id,benchmark_run_id,result.status,result.session_id,result.job_id,result.textual_response,json.dumps(result.evidence),json.dumps(result.raw),result.latency_ms,result.operations_charged,result.error,now()))
        return self.get_run(run_id)

    def batch_preview(self, case_ids: list[int], max_requests: int, max_operations: int) -> dict[str, Any]:
        if len(case_ids)!=len(set(case_ids)): raise ValueError("case_ids must be unique")
        if not case_ids: raise ValueError("select at least one case")
        if max_requests<1 or max_requests>self.max_batch_cases: raise ValueError(f"max_requests must be between 1 and {self.max_batch_cases}")
        if max_operations<1 or max_operations>self.max_batch_operations: raise ValueError(f"max_operations must be between 1 and {self.max_batch_operations}")
        if len(case_ids)>max_requests: raise ValueError("selected case count exceeds maximum requests")
        rows=[]
        benchmark_run_id=self.current_benchmark_run()["id"]
        self._ensure_benchmark_run_writable(benchmark_run_id)
        for cid in case_ids:
            if not self.db.one("SELECT 1 FROM benchmark_run_cases WHERE benchmark_run_id=? AND case_id=?",(benchmark_run_id,cid)): raise ValueError(f"case is not part of this benchmark run: {cid}")
            self.verify_case_integrity(cid)
            row=self.db.one("""SELECT c.id,c.external_case_id,c.instruction,c.case_type,d.name document_name,d.filename FROM cases c JOIN documents d ON d.id=c.document_id WHERE c.id=?""",(cid,))
            if not row: raise ValueError(f"case not found: {cid}")
            rows.append(row)
        return {"selected_case_ids":[r["external_case_id"] or str(r["id"]) for r in rows],"cases":rows,"selected_count":len(rows),"maximum_requests":max_requests,"operation_cap":max_operations}

    def run_batch(self, case_ids: list[int], max_requests: int, max_operations: int, confirmed: bool=False, benchmark_run_id: int | None=None) -> dict[str, Any]:
        preview=self.batch_preview(case_ids,max_requests,max_operations)
        if not confirmed: raise ValueError("explicit confirmation is required before batch execution")
        runs=[]; operations=0
        for case_id in case_ids:
            if operations>=max_operations: break
            run=self.run_case(case_id,benchmark_run_id); runs.append(run); operations+=int(run.get("operations_charged") or 0)
        return {"runs":runs,"cases_run":len(runs),"operations_charged":operations,"stopped_at_cap":len(runs)<len(case_ids) or operations>=max_operations,"preview":preview}

    def get_run(self, run_id: int) -> dict[str, Any]:
        run=self.db.one("""SELECT r.*,f.name failure_category,b.read_only benchmark_run_read_only FROM runs r LEFT JOIN failure_categories f ON f.id=r.failure_category_id JOIN benchmark_runs b ON b.id=r.benchmark_run_id WHERE r.id=?""",(run_id,))
        if not run: raise ValueError("run not found")
        run["failure_category_stored"]=run.get("failure_category")
        run["failure_category"]=simplify_failure_category(run.get("failure_category")) or run.get("failure_category")
        return self.db.decode_run(run)

    def get_applied_verification(self, run_id: int) -> dict[str, Any] | None:
        row=self.db.one("SELECT * FROM applied_verifications WHERE run_id=?",(run_id,))
        if not row: return None
        decoded=self.db.decode_applied(row)
        decoded["approval_actions"]=self.db.all("SELECT id,batch_fingerprint,status,submitted_at,error FROM approval_actions WHERE run_id=? ORDER BY id",(run_id,))
        return decoded

    def get_guided_recovery(self, run_id: int) -> dict[str, Any] | None:
        decoded=self.db.decode_recovery(self.db.one("SELECT * FROM guided_recoveries WHERE original_run_id=?",(run_id,)))
        if not decoded: return None
        # Version 1 of guided recovery submitted a redundant second chat message.
        # Repair those saved session_busy records from the already-stored revised
        # pending batch; this performs no network request.
        rejection=(decoded.get("recovery_raw_response") or {}).get("rejection") or decoded.get("rejection_response") or {}
        rejection_job=rejection.get("job") if isinstance(rejection,dict) else None
        pending=((rejection_job or {}).get("metadata") or {}).get("pending_changes") or []
        if decoded.get("recovery_status")=="error" and pending:
            run=self.get_run(run_id); structure=(run.get("evidence") or {}).get("chunk_heading_paths") or {}
            resolved=resolve_pending_changes(pending,structure)
            paths=list(dict.fromkeys(x.get("resolved_section_path") for x in resolved if x.get("resolved_section_path")))
            self.db.execute("""UPDATE guided_recoveries SET recovery_job_id=?,recovery_status=?,recovery_pending_changes_json=?,recovery_target_path=?,recovery_raw_response_json=?,recovery_operations=?,error=NULL,updated_at=? WHERE original_run_id=?""",
              ((rejection_job or {}).get("job_id"),(rejection_job or {}).get("status") or "awaiting_approval",json.dumps(resolved),paths[0] if len(paths)==1 else None,json.dumps({"rejection":rejection}),self._reported_operations(rejection_job),now(),run_id))
            return self.db.decode_recovery(self.db.one("SELECT * FROM guided_recoveries WHERE original_run_id=?",(run_id,)))
        return decoded

    @staticmethod
    def _reported_operations(payload: dict[str, Any] | None) -> int:
        payload=payload or {}; usage=payload.get("usage") or (payload.get("result") or {}).get("usage") or {}
        return int(usage.get("ops_charged") or (1 if usage.get("was_billable") else 0))

    def start_guided_recovery(self, run_id: int, guidance: str) -> dict[str, Any]:
        self._ensure_execution_writable(run_id)
        guidance=guidance.strip()
        if not guidance: raise ValueError("guidance is required")
        run=self.get_run(run_id); case=self.db.one("SELECT * FROM cases WHERE id=?",(run["case_id"],))
        pending=(run.get("evidence") or {}).get("pending_changes") or []
        job_meta=((run.get("raw_response") or {}).get("job") or {}).get("metadata") or {}
        if not case or case.get("case_type")!="edit" or run.get("status")!="awaiting_approval" or not pending:
            raise ValueError("guided recovery is available only for pending edit proposals")
        if job_meta.get("awaiting_kind")=="continue_prompt": raise ValueError("guided recovery cannot reject a continuation prompt")
        if self.get_applied_verification(run_id): raise ValueError("this proposal has already entered the approval flow")
        existing=self.get_guided_recovery(run_id)
        if existing:
            existing["duplicate_submit_prevented"]=True; return existing
        if not run.get("session_id") or not run.get("job_id"): raise ValueError("run has no SuperDocs session or job")
        change_ids=[str(x.get("change_id")) for x in pending if x.get("change_id")]
        if not change_ids: raise ValueError("pending changes have no rejection identifiers")
        paths=list(dict.fromkeys(x.get("resolved_section_path") for x in pending if x.get("resolved_section_path")))
        timestamp=now()
        try:
            self.db.execute("""INSERT INTO guided_recoveries(original_run_id,original_change_ids_json,original_pending_changes_json,original_target_path,guidance_text,recovery_session_id,recovery_status,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?)""",(run_id,json.dumps(change_ids),json.dumps(pending),paths[0] if len(paths)==1 else None,guidance,run["session_id"],"submitting",timestamp,timestamp))
        except sqlite3.IntegrityError:
            result=self.get_guided_recovery(run_id) or {}; result["duplicate_submit_prevented"]=True; return result
        started=time.perf_counter(); rejection=None; rejection_job=None
        try:
            if not self.client: raise SuperDocsError("SuperDocs client is not configured")
            decisions=[{"change_id":x["change_id"],"approved":False,"feedback":guidance} for x in pending]
            rejection=self.client.decide_changes(run["session_id"],run["job_id"],decisions)
            rejection_job=self.client.poll_after_approval(run["job_id"],change_ids)
            rejection_evidence={"decision":rejection,"job":rejection_job}
            metadata=rejection_job.get("metadata") or {}; structure=(run.get("evidence") or {}).get("chunk_heading_paths") or {}
            resolved=resolve_pending_changes(metadata.get("pending_changes") or [],structure)
            recovery_paths=list(dict.fromkeys(x.get("resolved_section_path") for x in resolved if x.get("resolved_section_path")))
            operations=self._reported_operations(rejection_job)
            raw={"rejection":rejection_evidence}
            self.db.execute("""UPDATE guided_recoveries SET recovery_status=?,recovery_pending_changes_json=?,recovery_target_path=?,recovery_raw_response_json=?,recovery_latency_ms=?,recovery_operations=?,error=?,updated_at=? WHERE original_run_id=?""",
              (rejection_job.get("status") or "unknown",json.dumps(resolved),recovery_paths[0] if len(recovery_paths)==1 else None,json.dumps(raw),(time.perf_counter()-started)*1000,operations,rejection_job.get("error"),now(),run_id))
            self.db.execute("UPDATE guided_recoveries SET recovery_job_id=?,rejected_at=?,rejection_response_json=? WHERE original_run_id=?",(rejection_job.get("job_id") or run["job_id"],now(),json.dumps(rejection_evidence),run_id))
        except Exception as exc:
            raw={"rejection":{"decision":rejection,"job":rejection_job}}
            self.db.execute("UPDATE guided_recoveries SET recovery_status='error',recovery_raw_response_json=?,recovery_latency_ms=?,error=?,updated_at=? WHERE original_run_id=?",(json.dumps(raw),(time.perf_counter()-started)*1000,str(exc),now(),run_id))
            raise
        return self.get_guided_recovery(run_id) or {}

    def adjudicate_guided_recovery(self, run_id: int, verdict: str, note: str|None=None) -> dict[str, Any]:
        self._ensure_execution_writable(run_id)
        if verdict not in {"recovered","not_recovered","ambiguous"}: raise ValueError("invalid recovery result")
        if not self.get_guided_recovery(run_id): raise ValueError("guided recovery not found")
        self.db.execute("UPDATE guided_recoveries SET recovery_verdict=?,recovery_note=?,updated_at=? WHERE original_run_id=?",(verdict,note,now(),run_id))
        return self.get_guided_recovery(run_id) or {}

    def guided_recovery_summary(self, benchmark_run_id: int | None=None) -> dict[str, Any]:
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
        rows=self.db.all("""SELECT g.recovery_verdict,g.recovery_operations FROM guided_recoveries g
          JOIN runs r ON r.id=g.original_run_id JOIN cases c ON c.id=r.case_id
          WHERE r.benchmark_run_id=? AND c.external_case_id IS NOT NULL""",(benchmark_run_id,))
        recovered=sum(x.get("recovery_verdict")=="recovered" for x in rows)
        adjudicated=sum(bool(x.get("recovery_verdict")) for x in rows)
        return {"cases_attempted":len(rows),"cases_recovered":recovered,
          "cases_not_recovered":sum(x.get("recovery_verdict")=="not_recovered" for x in rows),
          "cannot_determine":sum(x.get("recovery_verdict")=="ambiguous" for x in rows),
          "awaiting_evaluation":len(rows)-adjudicated,
          "recovery_rate":recovered/adjudicated if adjudicated else None,
          "additional_api_operations":sum(int(x.get("recovery_operations") or 0) for x in rows),"dollar_spend_usd":None}

    def applied_verification_summary(self, benchmark_run_id: int | None=None) -> dict[str, Any]:
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
        rows=self.db.all("""SELECT a.applied_target_correct,a.unrelated_changes_detected
          FROM applied_verifications a JOIN runs r ON r.id=a.run_id JOIN cases c ON c.id=r.case_id
          WHERE r.benchmark_run_id=? AND c.external_case_id IS NOT NULL""",(benchmark_run_id,))
        return {"verified":len(rows),
          "landed_in_intended_section":sum(x.get("applied_target_correct")==1 for x in rows),
          "did_not_land_correctly":sum(x.get("applied_target_correct")==0 for x in rows),
          "cannot_determine":sum(x.get("applied_target_correct") is None for x in rows),
          "unrelated_changes_detected":sum(x.get("unrelated_changes_detected")==1 for x in rows)}

    def viewer_html(self, run_id: int, stage: str="pre") -> str:
        run=self.get_run(run_id)
        case=self.db.one("SELECT * FROM cases WHERE id=?",(run["case_id"],))
        if not case: raise ValueError("case not found")
        raw=run.get("raw_response") or {}; pre=((raw.get("upload") or {}).get("html"))
        if not pre: raise ValueError("stored upload HTML is unavailable for this run")
        applied=self.get_applied_verification(run_id)
        document_html=applied.get("post_approval_html") if stage=="post" and applied else pre
        if stage=="post" and not document_html: raise ValueError("post-approval HTML is unavailable")
        recovery=self.get_guided_recovery(run_id)
        pending=(recovery.get("recovery_pending_changes") or []) if stage=="recovery" and recovery else ((applied.get("pending_changes") or []) if applied and applied.get("approval_status")=="additional_approval_required" else (run.get("evidence") or {}).get("pending_changes") or [])
        expected_path=case.get("expected_section_path") or case.get("expected_section")
        path_map=(run.get("evidence") or {}).get("chunk_heading_paths") or {}
        expected_chunks=[chunk_id for chunk_id,path in path_map.items() if path==expected_path or (expected_path and path.startswith(expected_path+" > "))]
        proposed=[]
        for change in pending:
            target=change.get("insert_after_chunk_id") if change.get("operation")=="create" else change.get("chunk_id")
            if target: proposed.append(target)
        applied_ids=[]
        if applied:
            applied_ids=(applied.get("changed_chunk_ids") or [])+(applied.get("new_chunk_ids") or [])+(applied.get("deleted_chunk_ids") or [])
        return render_annotated_document(document_html,expected_path,proposed,applied_ids,expected_chunks or None)

    @staticmethod
    def _documents(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload,list): return [item for item in payload if isinstance(item,dict)]
        if isinstance(payload,dict):
            for key in ("documents","items"):
                if isinstance(payload.get(key),list): return [item for item in payload[key] if isinstance(item,dict)]
        return []

    def approve_test_edit(self, run_id: int) -> dict[str, Any]:
        self._ensure_execution_writable(run_id)
        run=self.get_run(run_id)
        case=self.db.one("SELECT * FROM cases WHERE id=?",(run["case_id"],))
        if not case or case["case_type"]!="edit": raise ValueError("approval is available only for edit cases")
        if not run.get("session_id") or not run.get("job_id"): raise ValueError("run has no async job awaiting approval")
        applied=self.get_applied_verification(run_id)
        original_pending=(run.get("evidence") or {}).get("pending_changes") or []
        pending=(applied.get("pending_changes") or []) if applied and applied.get("approval_status")=="additional_approval_required" else original_pending
        job_context=(applied.get("post_job") if applied else None) or ((run.get("raw_response") or {}).get("job") or {})
        metadata=job_context.get("metadata") or {}
        if metadata.get("awaiting_kind")=="continue_prompt": raise ValueError("this job is waiting for a continuation decision, not change approval")
        if not pending: raise ValueError("run has no pending changes to approve")
        if run.get("status")!="awaiting_approval" and not (applied and applied.get("approval_status")=="additional_approval_required"):
            raise ValueError("run is not awaiting change approval")
        change_ids=sorted(str(item.get("change_id")) for item in pending if item.get("change_id"))
        if not change_ids: raise ValueError("pending changes have no approval identifiers")
        fingerprint=hashlib.sha256(json.dumps({"job_id":run["job_id"],"change_ids":change_ids},sort_keys=True).encode()).hexdigest()
        existing=self.db.one("SELECT id,status FROM approval_actions WHERE run_id=? AND batch_fingerprint=?",(run_id,fingerprint))
        if existing:
            result=self.get_applied_verification(run_id) or {}
            result["duplicate_approval_prevented"]=True
            return result
        pre=((run.get("raw_response") or {}).get("upload") or {}).get("html")
        if not pre: raise ValueError("stored pre-approval HTML is unavailable")
        proposal_paths=list(dict.fromkeys(item.get("resolved_section_path") for item in pending if item.get("resolved_section_path")))
        timestamp=now()
        try:
            with self.db.connect() as db:
                db.execute("""INSERT INTO applied_verifications(run_id,proposal_target_path,approval_status,approval_submitted_at,pre_approval_html,pending_changes_json,created_at,updated_at)
                  VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET approval_status=excluded.approval_status,approval_submitted_at=excluded.approval_submitted_at,pending_changes_json=excluded.pending_changes_json,updated_at=excluded.updated_at""",
                  (run_id,proposal_paths[0] if len(proposal_paths)==1 else None,"submitting",timestamp,pre,json.dumps(pending),timestamp,timestamp))
                db.execute("INSERT INTO approval_actions(run_id,batch_fingerprint,change_ids_json,changes_json,status,submitted_at) VALUES (?,?,?,?,?,?)",
                  (run_id,fingerprint,json.dumps(change_ids),json.dumps(pending),"submitting",timestamp))
        except sqlite3.IntegrityError:
            result=self.get_applied_verification(run_id) or {}
            result["duplicate_approval_prevented"]=True
            return result
        decisions=[{"change_id":item["change_id"],"approved":True} for item in pending]
        try:
            response=self.client.decide_changes(run["session_id"],run["job_id"],decisions) if self.client else None
            if response is None: raise SuperDocsError("SuperDocs client is not configured")
            self.db.execute("UPDATE approval_actions SET status='submitted',response_json=? WHERE run_id=? AND batch_fingerprint=?",(json.dumps(response),run_id,fingerprint))
            self.db.execute("UPDATE applied_verifications SET approval_status='submitted',updated_at=? WHERE run_id=?",(now(),run_id))
        except Exception as exc:
            self.db.execute("UPDATE approval_actions SET status='failed',error=? WHERE run_id=? AND batch_fingerprint=?",(str(exc),run_id,fingerprint))
            self.db.execute("UPDATE applied_verifications SET approval_status='submission_failed',post_approval_status='submission_failed',updated_at=? WHERE run_id=?",(now(),run_id))
            raise
        try:
            job=self.client.poll_after_approval(run["job_id"],change_ids)
        except Exception as exc:
            self.db.execute("UPDATE approval_actions SET error=? WHERE run_id=? AND batch_fingerprint=?",(str(exc),run_id,fingerprint))
            self.db.execute("UPDATE applied_verifications SET post_approval_status='polling_failed',updated_at=? WHERE run_id=?",(now(),run_id))
            raise
        status=job.get("status"); metadata=job.get("metadata") or {}
        if status=="awaiting_approval":
            if metadata.get("awaiting_kind")=="continue_prompt":
                approval_status="continuation_required"; next_pending=[]
            else:
                approval_status="additional_approval_required"
                structure=parse_document_html(pre)
                next_pending=resolve_changes(metadata.get("pending_changes") or [],structure)
            self.db.execute("""UPDATE applied_verifications SET approval_status=?,post_approval_status=?,pending_changes_json=?,post_job_json=?,updated_at=? WHERE run_id=?""",
              (approval_status,status,json.dumps(next_pending),json.dumps(job),now(),run_id))
            return self.get_applied_verification(run_id)
        if status in {"failed","cancelled"}:
            self.db.execute("UPDATE applied_verifications SET approval_status='finished',post_approval_status=?,post_job_json=?,updated_at=? WHERE run_id=?",(status,json.dumps(job),now(),run_id))
            return self.get_applied_verification(run_id)
        if status!="completed": raise SuperDocsError(f"unexpected post-approval job status: {status}")
        try:
            payload=self.client.list_session_documents(run["session_id"])
            documents=self._documents(payload)
            all_changes=[]
            for action in self.db.all("SELECT changes_json FROM approval_actions WHERE run_id=? AND status='submitted' ORDER BY id",(run_id,)):
                all_changes.extend(json.loads(action["changes_json"] or "[]"))
            requested_ids=list(dict.fromkeys(item.get("document_id") for item in all_changes if item.get("document_id")))
            selected=None
            if requested_ids:
                selected=next((doc for doc in documents if doc.get("document_id") in requested_ids or doc.get("durable_document_id") in requested_ids),None)
            if selected is None and len(documents)==1: selected=documents[0]
            if selected is None: raise SuperDocsError("could not identify the edited document in the session")
            post=selected.get("html")
            if not post: raise SuperDocsError("updated session document did not include HTML")
            evidence=diff_documents(pre,post,all_changes)
        except Exception:
            self.db.execute("UPDATE applied_verifications SET post_approval_status='document_fetch_failed',post_job_json=?,updated_at=? WHERE run_id=?",(json.dumps(job),now(),run_id))
            raise
        self.db.execute("""UPDATE applied_verifications SET approval_status='completed',post_approval_status='completed',applied_target_path=?,applied_target_paths_json=?,create_placements_json=?,changed_chunk_ids_json=?,new_chunk_ids_json=?,deleted_chunk_ids_json=?,unrelated_chunk_ids_json=?,unrelated_changes_detected=?,post_approval_html=?,pending_changes_json='[]',post_job_json=?,session_document_id=?,updated_at=? WHERE run_id=?""",
          (evidence["applied_target_path"],json.dumps(evidence["applied_target_paths"]),json.dumps(evidence["create_placements"]),json.dumps(evidence["changed_chunk_ids"]),json.dumps(evidence["new_chunk_ids"]),json.dumps(evidence["deleted_chunk_ids"]),json.dumps(evidence["unrelated_chunk_ids"]),int(evidence["unrelated_changes_detected"]),post,json.dumps(job),selected.get("document_id") or selected.get("durable_document_id"),now(),run_id))
        return self.get_applied_verification(run_id)

    def save_applied_verification(self, run_id: int, proposal_target_correct: bool | None, applied_target_correct: bool | None, notes: str | None) -> dict[str, Any]:
        self._ensure_execution_writable(run_id)
        if not self.db.one("SELECT id FROM applied_verifications WHERE run_id=?",(run_id,)): raise ValueError("applied verification is not available")
        self.db.execute("UPDATE applied_verifications SET proposal_target_correct=?,applied_target_correct=?,applied_verification_notes=?,updated_at=? WHERE run_id=?",
          (None if proposal_target_correct is None else int(proposal_target_correct),None if applied_target_correct is None else int(applied_target_correct),notes,now(),run_id))
        return self.get_applied_verification(run_id)

    def adjudicate(self, run_id: int, verdict: str, failure_category_id: int | None, note: str | None) -> dict[str, Any]:
        self._ensure_execution_writable(run_id)
        if verdict not in {"pass","fail","ambiguous"}: raise ValueError("invalid verdict")
        if verdict=="fail" and failure_category_id is None: raise ValueError("failure category is required for fail")
        if failure_category_id and not self.db.one("SELECT id FROM failure_categories WHERE id=? AND active=1",(failure_category_id,)): raise ValueError("failure category not found or inactive")
        self.db.execute("UPDATE runs SET verdict=?,failure_category_id=?,adjudication_note=?,adjudicated_at=? WHERE id=?",(verdict,failure_category_id if verdict=="fail" else None,note,now(),run_id)); return self.get_run(run_id)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        if not values: return None
        values=sorted(values); index=(len(values)-1)*percentile; lower=math.floor(index); upper=math.ceil(index)
        return values[lower] if lower==upper else values[lower]+(values[upper]-values[lower])*(index-lower)

    def metrics(self, benchmark_run_id: int | None=None) -> dict[str, Any]:
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
        if not self.db.one("SELECT id FROM benchmark_runs WHERE id=?",(benchmark_run_id,)): raise ValueError("benchmark run not found")
        official_cases=self.db.one("SELECT COUNT(*) n FROM benchmark_run_cases WHERE benchmark_run_id=?",(benchmark_run_id,))["n"]
        official_documents=self.db.one("""SELECT COUNT(DISTINCT c.document_id) n FROM benchmark_run_cases brc JOIN cases c ON c.id=brc.case_id WHERE brc.benchmark_run_id=?""",(benchmark_run_id,))["n"]
        latest=self.db.all("""WITH latest AS (
          SELECT r.case_id,MAX(r.id) id FROM runs r JOIN benchmark_run_cases brc ON brc.case_id=r.case_id AND brc.benchmark_run_id=r.benchmark_run_id WHERE r.benchmark_run_id=? GROUP BY r.case_id
        ) SELECT r.*,f.name failure_category,c.external_case_id,c.case_type,c.difficulty,c.expected_behavior,c.capability_tested,
          c.expected_section_path,c.acceptable_section_paths_json,c.must_not_target_json
          FROM latest l JOIN runs r ON r.id=l.id JOIN cases c ON c.id=r.case_id
          LEFT JOIN failure_categories f ON f.id=r.failure_category_id""",(benchmark_run_id,))
        for row in latest:
            row["strict_verdict"]=row.get("verdict")
            row.update(assess_targeting(row))
        adjudicated=[r for r in latest if r.get("verdict")]; latencies=[float(r["latency_ms"]) for r in latest if r.get("status")!="error" and r.get("latency_ms") is not None]
        def grouped(field):
            out=[]
            for value in sorted({r.get(field) or "unspecified" for r in latest}):
                rows=[r for r in latest if (r.get(field) or "unspecified")==value]
                out.append({field:value,"total":len(rows),"pass":sum(r.get("verdict")=="pass" for r in rows),"fail":sum(r.get("verdict")=="fail" for r in rows),"ambiguous":sum(r.get("verdict")=="ambiguous" for r in rows),"system_error":sum(r.get("status")=="error" for r in rows)})
            return out
        passed=sum(r.get("verdict")=="pass" for r in adjudicated)
        operations=sum(int(r.get("operations_charged") or 0) for r in latest)
        official_cases_run=self.db.one("""SELECT COUNT(DISTINCT r.case_id) count FROM runs r JOIN benchmark_run_cases brc ON brc.case_id=r.case_id AND brc.benchmark_run_id=r.benchmark_run_id
          WHERE r.benchmark_run_id=?""",(benchmark_run_id,))["count"]
        failures=[]
        for category,definition in PUBLIC_FAILURE_DEFINITIONS.items():
            count=sum(r.get("simplified_failure_category")==category for r in latest)
            if count: failures.append({"name":category,"definition":definition,"count":count})
        targeting=verdict_summary(latest,"targeting_verdict")
        targeting_by_type={kind:verdict_summary([r for r in latest if r.get("case_type")==kind],"targeting_verdict") for kind in ("search","edit")}
        strict_by_type={kind:verdict_summary([r for r in latest if r.get("case_type")==kind],"strict_verdict") for kind in ("search","edit")}
        return {"benchmark_run_id":benchmark_run_id,"scope":"official","official_cases":official_cases,"official_cases_run":official_cases_run,"official_run_complete":official_cases_run==official_cases,"official_documents":official_documents,"total_cases":official_cases,"evaluated":len(adjudicated),"unevaluated":official_cases-len(adjudicated),"pass":passed,"fail":sum(r.get("verdict")=="fail" for r in adjudicated),"ambiguous":sum(r.get("verdict")=="ambiguous" for r in adjudicated),"pass_rate":passed/len(adjudicated) if adjudicated else 0,"strict":verdict_summary(latest,"strict_verdict"),"targeting":targeting,"targeting_by_case_type":targeting_by_type,"strict_by_case_type":strict_by_type,"system_error":sum(r.get("status")=="error" for r in latest),"average_latency_ms":sum(latencies)/len(latencies) if latencies else None,"p50_latency_ms":self._percentile(latencies,.5),"p95_latency_ms":self._percentile(latencies,.95),"total_operations_charged":operations,"budget_cap_operations":self.max_batch_operations,"within_budget":operations<=self.max_batch_operations,"total_spend_usd":None,"applied_verification":self.applied_verification_summary(benchmark_run_id),"guided_recovery":self.guided_recovery_summary(benchmark_run_id),"by_case_type":grouped("case_type"),"by_difficulty":grouped("difficulty"),"by_expected_behavior":grouped("expected_behavior"),"by_capability":grouped("capability_tested"),"by_failure_category":failures}
