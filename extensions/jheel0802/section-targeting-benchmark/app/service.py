from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .db import Database, now
from .superdocs import RunResult, SuperDocsClient, SuperDocsError


class BenchmarkService:
    def __init__(self, db: Database, client: SuperDocsClient | None, max_batch_cases: int = 5, max_batch_operations: int = 5):
        self.db, self.client = db, client
        self.max_batch_cases, self.max_batch_operations = max_batch_cases, max_batch_operations

    def current_benchmark_run(self) -> dict[str, Any]:
        row=self.db.one("SELECT * FROM benchmark_runs WHERE selected=1 ORDER BY id DESC LIMIT 1")
        if not row: raise ValueError("no benchmark run is selected")
        return row

    def list_benchmark_runs(self) -> list[dict[str, Any]]:
        return self.db.all("""SELECT b.*,COUNT(r.id) execution_attempts,
          COUNT(DISTINCT CASE WHEN c.external_case_id IS NOT NULL THEN r.case_id END) official_cases_run,
          (SELECT COUNT(*) FROM cases WHERE external_case_id IS NOT NULL) official_cases_total
          FROM benchmark_runs b LEFT JOIN runs r ON r.benchmark_run_id=b.id
          LEFT JOIN cases c ON c.id=r.case_id GROUP BY b.id ORDER BY b.id DESC""")

    def start_benchmark_run(self) -> dict[str, Any]:
        with self.db.connect() as db:
            number=db.execute("SELECT COUNT(*)+1 FROM benchmark_runs").fetchone()[0]
            db.execute("UPDATE benchmark_runs SET selected=0")
            run_id=db.execute("INSERT INTO benchmark_runs(name,selected,created_at) VALUES (?,?,?)",(f"Benchmark run {number}",1,now())).lastrowid
        return self.db.one("SELECT * FROM benchmark_runs WHERE id=?",(run_id,))

    def select_benchmark_run(self, benchmark_run_id: int) -> dict[str, Any]:
        if not self.db.one("SELECT id FROM benchmark_runs WHERE id=?",(benchmark_run_id,)): raise ValueError("benchmark run not found")
        with self.db.connect() as db:
            db.execute("UPDATE benchmark_runs SET selected=0")
            db.execute("UPDATE benchmark_runs SET selected=1 WHERE id=?",(benchmark_run_id,))
        return self.current_benchmark_run()

    def create_document(self, payload: dict[str, Any], content: bytes) -> int:
        sha=hashlib.sha256(content).hexdigest()
        return self.db.execute("INSERT INTO documents(name,filename,content_type,content,actual_sha256,created_at) VALUES (?,?,?,?,?,?)",(payload["name"],payload["filename"],payload.get("content_type") or "application/octet-stream",content,sha,now()))

    def create_case(self, payload: dict[str, Any]) -> int:
        if payload["case_type"] not in {"search","edit"}: raise ValueError("case_type must be search or edit")
        if payload.get("expected_behavior","unique_target") not in {"unique_target","acceptable_set","should_clarify","no_target"}: raise ValueError("invalid expected_behavior")
        if not self.db.one("SELECT id FROM documents WHERE id=?",(payload["document_id"],)): raise ValueError("document not found")
        expected_path=payload.get("expected_section_path") or payload.get("expected_section")
        return self.db.execute("""INSERT INTO cases(title,case_type,document_id,instruction,expected_section,expected_answer,notes,external_case_id,difficulty,expected_behavior,expected_section_path,acceptable_section_paths_json,expected_edit_scope,must_not_target_json,capability_tested,likely_failure_category,rationale,fixture_version,expected_document_sha256,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
          payload.get("title") or payload.get("external_case_id") or "Benchmark case",payload["case_type"],payload["document_id"],payload["instruction"],expected_path or "",payload.get("expected_answer"),payload.get("notes"),payload.get("external_case_id"),payload.get("difficulty"),payload.get("expected_behavior","unique_target"),expected_path,json.dumps(payload.get("acceptable_section_paths") or []),payload.get("expected_edit_scope"),json.dumps(payload.get("must_not_target") or []),payload.get("capability_tested"),payload.get("likely_failure_category"),payload.get("rationale"),payload.get("fixture_version"),payload.get("expected_document_sha256"),now()))

    def import_corpus(self, manifest_path: str | Path) -> dict[str, Any]:
        path=Path(manifest_path).resolve(); data=json.loads(path.read_text()); document_dir=path.parent/"documents"
        if data.get("document_count")!=14 or data.get("case_count")!=40: raise ValueError("manifest must describe the frozen 14-document / 40-case corpus")
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
        return {"status":"imported","fixture_version":data["fixture_version"],"documents_created":created_docs,"cases_created":created_cases,"documents_total":14,"cases_total":40}

    def verify_case_integrity(self, case_id: int) -> dict[str, Any]:
        row=self.db.one("""SELECT c.external_case_id,c.expected_document_sha256,d.id document_id,d.filename,d.content,d.expected_sha256 FROM cases c JOIN documents d ON d.id=c.document_id WHERE c.id=?""",(case_id,))
        if not row: raise ValueError("case not found")
        expected=row.get("expected_document_sha256") or row.get("expected_sha256")
        actual=hashlib.sha256(row["content"]).hexdigest()
        if expected and actual!=expected: raise ValueError(f"frozen fixture changed for {row.get('external_case_id') or case_id} ({row['filename']}): expected SHA-256 {expected}, got {actual}; run blocked")
        return {"expected_sha256":expected,"actual_sha256":actual,"verified":not expected or expected==actual}

    def run_case(self, case_id: int, benchmark_run_id: int | None=None) -> dict[str, Any]:
        self.verify_case_integrity(case_id)
        case=self.db.one("SELECT * FROM cases WHERE id=?",(case_id,)); document=self.db.one("SELECT * FROM documents WHERE id=?",(case["document_id"],)) if case else None
        if not case or not document: raise ValueError("case not found")
        if self.client is None: raise ValueError("SuperDocs client is not configured")
        try: result=self.client.run(self.db.decode_case(case),document)
        except SuperDocsError as exc: result=RunResult("error","",None,{}, {},0,error=str(exc))
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
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
        for cid in case_ids:
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
        run=self.db.one("SELECT * FROM runs WHERE id=?",(run_id,))
        if not run: raise ValueError("run not found")
        return self.db.decode_run(run)

    def adjudicate(self, run_id: int, verdict: str, failure_category_id: int | None, note: str | None) -> dict[str, Any]:
        if verdict not in {"pass","fail","ambiguous"}: raise ValueError("invalid verdict")
        if verdict=="fail" and failure_category_id is None: raise ValueError("failure category is required for fail")
        if failure_category_id and not self.db.one("SELECT id FROM failure_categories WHERE id=? AND active=1",(failure_category_id,)): raise ValueError("failure category not found or inactive")
        self.db.execute("UPDATE runs SET verdict=?,failure_category_id=?,adjudication_note=?,adjudicated_at=? WHERE id=?",(verdict,failure_category_id if verdict=="fail" else None,note,now(),run_id)); return self.get_run(run_id)

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        if not values: return None
        values=sorted(values); index=(len(values)-1)*percentile; lower=math.floor(index); upper=math.ceil(index)
        return values[lower] if lower==upper else values[lower]+(values[upper]-values[lower])*(index-lower)

    def metrics(self, include_custom: bool=False, benchmark_run_id: int | None=None) -> dict[str, Any]:
        benchmark_run_id=benchmark_run_id or self.current_benchmark_run()["id"]
        if not self.db.one("SELECT id FROM benchmark_runs WHERE id=?",(benchmark_run_id,)): raise ValueError("benchmark run not found")
        official_cases=self.db.one("SELECT COUNT(*) n FROM cases WHERE external_case_id IS NOT NULL")["n"]
        official_documents=self.db.one("SELECT COUNT(DISTINCT document_id) n FROM cases WHERE external_case_id IS NOT NULL")["n"]
        custom_cases=self.db.one("SELECT COUNT(*) n FROM cases WHERE external_case_id IS NULL")["n"]
        scope="" if include_custom else "AND c.external_case_id IS NOT NULL"
        cases_total=official_cases+custom_cases if include_custom else official_cases
        latest=self.db.all(f"""WITH latest AS (
          SELECT r.case_id,MAX(r.id) id FROM runs r JOIN cases c ON c.id=r.case_id WHERE r.benchmark_run_id=? {scope} GROUP BY r.case_id
        ) SELECT r.*,c.case_type,c.difficulty,c.expected_behavior,c.capability_tested
          FROM latest l JOIN runs r ON r.id=l.id JOIN cases c ON c.id=r.case_id""",(benchmark_run_id,))
        adjudicated=[r for r in latest if r.get("verdict")]; latencies=[float(r["latency_ms"]) for r in latest if r.get("status")!="error" and r.get("latency_ms") is not None]
        def grouped(field):
            out=[]
            for value in sorted({r.get(field) or "unspecified" for r in latest}):
                rows=[r for r in latest if (r.get(field) or "unspecified")==value]
                out.append({field:value,"total":len(rows),"pass":sum(r.get("verdict")=="pass" for r in rows),"fail":sum(r.get("verdict")=="fail" for r in rows),"ambiguous":sum(r.get("verdict")=="ambiguous" for r in rows),"system_error":sum(r.get("status")=="error" for r in rows)})
            return out
        passed=sum(r.get("verdict")=="pass" for r in adjudicated)
        operations=sum(int(r.get("operations_charged") or 0) for r in latest)
        run_scope="" if include_custom else "AND c.external_case_id IS NOT NULL"
        failures=self.db.all(f"""SELECT f.name,COUNT(*) count FROM runs r JOIN cases c ON c.id=r.case_id JOIN failure_categories f ON f.id=r.failure_category_id WHERE r.verdict='fail' AND r.benchmark_run_id=? {run_scope} GROUP BY f.id ORDER BY count DESC""",(benchmark_run_id,))
        return {"benchmark_run_id":benchmark_run_id,"scope":"all" if include_custom else "official","official_cases":official_cases,"official_documents":official_documents,"custom_cases":custom_cases,"total_cases":cases_total,"evaluated":len(adjudicated),"unevaluated":cases_total-len(adjudicated),"pass":passed,"fail":sum(r.get("verdict")=="fail" for r in adjudicated),"ambiguous":sum(r.get("verdict")=="ambiguous" for r in adjudicated),"system_error":sum(r.get("status")=="error" for r in latest),"pass_rate":passed/len(adjudicated) if adjudicated else 0,"average_latency_ms":sum(latencies)/len(latencies) if latencies else None,"p50_latency_ms":self._percentile(latencies,.5),"p95_latency_ms":self._percentile(latencies,.95),"total_operations_charged":operations,"total_spend_usd":None,"by_case_type":grouped("case_type"),"by_difficulty":grouped("difficulty"),"by_expected_behavior":grouped("expected_behavior"),"by_capability":grouped("capability_tested"),"by_failure_category":failures}
