from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .db import Database
from .service import BenchmarkService
from .superdocs import FakeSuperDocsClient, RealSuperDocsClient, SuperDocsError
from .targeting import PUBLIC_FAILURE_DEFINITIONS

PROJECT_ROOT=Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST=PROJECT_ROOT/"outputs"/"benchmark_corpus"/"benchmark_manifest.json"

class AdjudicationIn(BaseModel):
    verdict:str; failure_category_id:int|None=None; note:str|None=None
class TaxonomyIn(BaseModel): name:str
class BatchIn(BaseModel):
    case_ids:list[int]; max_requests:int; max_operations:int; confirmed:bool=False
class AppliedVerificationIn(BaseModel):
    proposal_target_correct:bool|None=None
    applied_target_correct:bool|None=None
    notes:str|None=None
class GuidedRecoveryIn(BaseModel):
    guidance:str=Field(min_length=1)
class GuidedRecoveryVerdictIn(BaseModel):
    verdict:str
    note:str|None=None
class BenchmarkRunSelectIn(BaseModel): benchmark_run_id:int

def create_app(settings:Settings|None=None,client:Any=None)->FastAPI:
    settings=settings or Settings.from_env(); db=Database(settings.db_path)
    if client is None: client=FakeSuperDocsClient() if settings.client_mode=="fake" else None
    service=BenchmarkService(db,client,settings.max_batch_cases,settings.max_batch_operations)
    app=FastAPI(title="SuperDocs Section Targeting Benchmark",version="1.0.0")
    app.state.db=db; app.state.service=service; app.state.settings=settings

    def get_service(require_client:bool=False)->BenchmarkService:
        if require_client and service.client is None:
            try: service.client=RealSuperDocsClient(settings)
            except SuperDocsError as exc: raise HTTPException(503,str(exc)) from exc
        return service

    @app.get("/api/config")
    def config(): return {"client_mode":settings.client_mode,"max_batch_cases":settings.max_batch_cases,"max_batch_operations":settings.max_batch_operations,"api_key_configured":bool(settings.api_key),"default_manifest":str(DEFAULT_MANIFEST)}

    @app.get("/api/benchmark-runs")
    def benchmark_runs(): return get_service().list_benchmark_runs()

    @app.get("/api/benchmark-runs/current")
    def current_benchmark_run(): return get_service().current_benchmark_run()

    @app.post("/api/benchmark-runs",status_code=201)
    def start_benchmark_run(): return get_service().start_benchmark_run()

    @app.put("/api/benchmark-runs/current")
    def select_benchmark_run(body:BenchmarkRunSelectIn):
        try: return get_service().select_benchmark_run(body.benchmark_run_id)
        except ValueError as exc: raise HTTPException(404,str(exc)) from exc

    @app.post("/api/corpus/import")
    def import_corpus():
        try: return get_service().import_corpus(DEFAULT_MANIFEST)
        except (ValueError,OSError,json.JSONDecodeError) as exc: raise HTTPException(400,str(exc)) from exc

    @app.get("/api/documents")
    def documents(): return db.all("SELECT id,name,filename,content_type,external_document_id,fixture_version,expected_sha256,actual_sha256,created_at FROM documents ORDER BY COALESCE(external_document_id,filename)")

    @app.get("/api/cases")
    def cases(document_id:int|None=None,case_type:str|None=None,difficulty:str|None=None,expected_behavior:str|None=None,capability:str|None=None,adjudication_state:str|None=None,benchmark_run_id:int|None=None):
        benchmark_run_id=benchmark_run_id or get_service().current_benchmark_run()["id"]
        sql="""SELECT c.*,d.name document_name,d.filename,
          (SELECT id FROM runs WHERE case_id=c.id AND benchmark_run_id=? ORDER BY id DESC LIMIT 1) latest_run_id,
          (SELECT verdict FROM runs WHERE case_id=c.id AND benchmark_run_id=? ORDER BY id DESC LIMIT 1) latest_verdict,
          (SELECT status FROM runs WHERE case_id=c.id AND benchmark_run_id=? ORDER BY id DESC LIMIT 1) latest_status
          FROM benchmark_run_cases brc JOIN cases c ON c.id=brc.case_id JOIN documents d ON d.id=c.document_id
          WHERE brc.benchmark_run_id=? AND c.external_case_id IS NOT NULL"""; params=[benchmark_run_id]*4
        filters=[("c.document_id",document_id),("c.case_type",case_type),("c.difficulty",difficulty),("c.expected_behavior",expected_behavior),("c.capability_tested",capability)]
        for column,value in filters:
            if value is not None: sql+=f" AND {column}=?"; params.append(value)
        if adjudication_state=="unevaluated": sql+=" AND NOT EXISTS(SELECT 1 FROM runs r WHERE r.case_id=c.id AND r.benchmark_run_id=? AND r.verdict IS NOT NULL)"; params.append(benchmark_run_id)
        elif adjudication_state in {"pass","fail","ambiguous"}: sql+=" AND (SELECT verdict FROM runs WHERE case_id=c.id AND benchmark_run_id=? ORDER BY id DESC LIMIT 1)=?"; params.extend((benchmark_run_id,adjudication_state))
        elif adjudication_state=="system_error": sql+=" AND (SELECT status FROM runs WHERE case_id=c.id AND benchmark_run_id=? ORDER BY id DESC LIMIT 1)='error'"; params.append(benchmark_run_id)
        rows=db.all(sql+" ORDER BY c.external_case_id",tuple(params))
        return [db.decode_case(row) for row in rows]

    @app.get("/api/runs")
    def runs(benchmark_run_id:int|None=None):
        benchmark_run_id=benchmark_run_id or get_service().current_benchmark_run()["id"]
        return db.all("""SELECT r.id,r.case_id,r.benchmark_run_id,r.status,r.latency_ms,r.operations_charged,r.error,r.verdict,r.created_at,c.title,c.external_case_id,c.case_type FROM runs r JOIN benchmark_run_cases brc ON brc.case_id=r.case_id AND brc.benchmark_run_id=r.benchmark_run_id JOIN cases c ON c.id=r.case_id WHERE r.benchmark_run_id=? ORDER BY r.id DESC""",(benchmark_run_id,))

    @app.get("/api/runs/{run_id}")
    def run(run_id:int):
        try: result=get_service().get_run(run_id)
        except ValueError as exc: raise HTTPException(404,str(exc)) from exc
        result["case"]=db.decode_case(db.one("SELECT c.*,d.name document_name,d.filename FROM cases c JOIN documents d ON d.id=c.document_id WHERE c.id=?",(result["case_id"],)))
        result["applied_verification"]=get_service().get_applied_verification(run_id)
        result["guided_recovery"]=get_service().get_guided_recovery(run_id)
        return result

    @app.get("/api/cases/{case_id}/integrity")
    def integrity(case_id:int):
        try: return get_service().verify_case_integrity(case_id)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post("/api/cases/{case_id}/run",status_code=201)
    def run_case(case_id:int):
        try: return get_service(True).run_case(case_id)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post("/api/runs/batch/preview")
    def batch_preview(body:BatchIn):
        try: return get_service().batch_preview(body.case_ids,body.max_requests,body.max_operations)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @app.post("/api/runs/batch",status_code=201)
    def run_batch(body:BatchIn):
        try: return get_service(True).run_batch(body.case_ids,body.max_requests,body.max_operations,body.confirmed)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @app.put("/api/runs/{run_id}/adjudication")
    def adjudicate(run_id:int,body:AdjudicationIn):
        try: return get_service().adjudicate(run_id,body.verdict,body.failure_category_id,body.note)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc

    @app.post("/api/runs/{run_id}/approval")
    def approve(run_id:int):
        try: return get_service(True).approve_test_edit(run_id)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        except SuperDocsError as exc: raise HTTPException(502,str(exc)) from exc

    @app.put("/api/runs/{run_id}/applied-verification")
    def applied_verification(run_id:int,body:AppliedVerificationIn):
        try: return get_service().save_applied_verification(run_id,body.proposal_target_correct,body.applied_target_correct,body.notes)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @app.post("/api/runs/{run_id}/guided-recovery")
    def guided_recovery(run_id:int,body:GuidedRecoveryIn):
        try: return get_service(True).start_guided_recovery(run_id,body.guidance)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
        except SuperDocsError as exc: raise HTTPException(502,str(exc)) from exc

    @app.put("/api/runs/{run_id}/guided-recovery/adjudication")
    def guided_recovery_adjudication(run_id:int,body:GuidedRecoveryVerdictIn):
        try: return get_service().adjudicate_guided_recovery(run_id,body.verdict,body.note)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc

    @app.get("/api/guided-recovery/summary")
    def guided_recovery_summary(benchmark_run_id:int|None=None): return get_service().guided_recovery_summary(benchmark_run_id)

    @app.get("/api/runs/{run_id}/viewer")
    def viewer(run_id:int,stage:str="pre"):
        if stage not in {"pre","post","recovery"}: raise HTTPException(400,"stage must be pre, post, or recovery")
        try: content=get_service().viewer_html(run_id,stage)
        except ValueError as exc: raise HTTPException(404,str(exc)) from exc
        return Response(content,media_type="text/html",headers={
          "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:",
          "X-Content-Type-Options":"nosniff",
        })

    @app.get("/api/runs/{run_id}/export")
    def export(run_id:int,format:str="docx"):
        if format not in {"docx","pdf","html","markdown","txt"}: raise HTTPException(400,"unsupported export format")
        run=get_service().get_run(run_id)
        if not run.get("session_id"): raise HTTPException(400,"run has no SuperDocs session")
        try: content,content_type=get_service(True).client.export(run["session_id"],format)
        except SuperDocsError as exc: raise HTTPException(502,str(exc)) from exc
        return Response(content,media_type=content_type,headers={"Content-Disposition":f'attachment; filename="benchmark-run-{run_id}.{format}"'})

    @app.get("/api/runs/{run_id}/preview")
    def preview(run_id:int):
        run=get_service().get_run(run_id)
        if not run.get("session_id"): raise HTTPException(400,"run has no SuperDocs session")
        try: content,_=get_service(True).client.export(run["session_id"],"html")
        except SuperDocsError as exc: raise HTTPException(502,str(exc)) from exc
        return Response(content,media_type="text/html",headers={"Content-Disposition":f'inline; filename="benchmark-run-{run_id}.html"'})

    @app.get("/api/taxonomy")
    def taxonomy(): return db.all("SELECT * FROM failure_categories WHERE active=1 ORDER BY id")
    @app.get("/api/taxonomy/definitions")
    def taxonomy_definitions(): return [{"name":name,"definition":definition} for name,definition in PUBLIC_FAILURE_DEFINITIONS.items()]
    @app.post("/api/taxonomy",status_code=201)
    def add_taxonomy(body:TaxonomyIn):
        try: cid=db.execute("INSERT INTO failure_categories(name) VALUES (?)",(body.name.strip(),))
        except Exception as exc: raise HTTPException(400,"category must be non-empty and unique") from exc
        return db.one("SELECT * FROM failure_categories WHERE id=?",(cid,))
    @app.delete("/api/taxonomy/{category_id}",status_code=204)
    def delete_taxonomy(category_id:int): db.execute("UPDATE failure_categories SET active=0 WHERE id=?",(category_id,)); return Response(status_code=204)
    @app.get("/api/metrics")
    def metrics(benchmark_run_id:int|None=None): return get_service().metrics(benchmark_run_id)

    static=Path(__file__).parent/"static"; app.mount("/static",StaticFiles(directory=static),name="static")
    @app.get("/",include_in_schema=False)
    def index(): return FileResponse(static/"index.html")
    return app

app=create_app()
