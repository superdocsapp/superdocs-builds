import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import DEFAULT_TAXONOMY, Database
from app.main import create_app
from app.service import BenchmarkService
from app.superdocs import FakeSuperDocsClient, build_chunk_heading_map, resolve_pending_changes

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"outputs"/"benchmark_corpus"/"benchmark_manifest.json"

@pytest.fixture
def setup(tmp_path):
    db=Database(str(tmp_path/"test.db")); fake=FakeSuperDocsClient(); service=BenchmarkService(db,fake,5,5)
    document_id=service.create_document({"name":"Projects","filename":"projects.html","content_type":"text/html"},b"<h1>Projects</h1><p>March 20</p>")
    return db,fake,service,document_id

def new_case(service,document_id,case_type="search",**overrides):
    payload={"title":"Target timeline","case_type":case_type,"document_id":document_id,"instruction":"What is the deadline?" if case_type=="search" else "Change the deadline.","expected_behavior":"unique_target","expected_section_path":"Projects > X > Timeline","expected_answer":"March 20","acceptable_section_paths":[],"must_not_target":["Projects > Y > Timeline"]}
    payload.update(overrides); return service.create_case(payload)

def test_case_creation_preserves_structured_fields(setup):
    db,_,service,did=setup; cid=new_case(service,did,external_case_id="X-C01",difficulty="hard",capability_tested="parent_context",expected_edit_scope="one section")
    case=db.decode_case(db.one("SELECT * FROM cases WHERE id=?",(cid,)))
    assert case["external_case_id"]=="X-C01" and case["difficulty"]=="hard"
    assert case["must_not_target"]==["Projects > Y > Timeline"] and case["acceptable_section_paths"]==[]

def test_manifest_import_all_fields_and_idempotency(tmp_path):
    db=Database(str(tmp_path/"corpus.db")); service=BenchmarkService(db,FakeSuperDocsClient())
    first=service.import_corpus(MANIFEST); second=service.import_corpus(MANIFEST)
    assert (first["documents_created"],first["cases_created"])==(14,40)
    assert (second["documents_created"],second["cases_created"])==(0,0)
    case=db.decode_case(db.one("SELECT * FROM cases WHERE external_case_id='D09-C01'"))
    source=next(c for c in json.loads(MANIFEST.read_text())["cases"] if c["case_id"]=="D09-C01")
    assert case["expected_behavior"]=="should_clarify"
    assert case["acceptable_section_paths"]==source["acceptable_section_paths"]
    assert case["must_not_target"]==source["must_not_target"]
    assert case["fixture_version"]==source["fixture_version"]
    assert case["expected_document_sha256"]==source["document_sha256"]

def test_manifest_import_rejects_sha_mismatch(tmp_path):
    source=json.loads(MANIFEST.read_text()); corpus=tmp_path/"corpus"; docs=corpus/"documents"; docs.mkdir(parents=True)
    for item in source["documents"]:
        original=MANIFEST.parent/"documents"/item["filename"]
        (docs/item["filename"]).write_bytes(original.read_bytes())
    (docs/source["documents"][0]["filename"]).write_bytes(b"changed")
    (corpus/"benchmark_manifest.json").write_text(json.dumps(source))
    with pytest.raises(ValueError,match="hash mismatch"): BenchmarkService(Database(str(tmp_path/"x.db")),FakeSuperDocsClient()).import_corpus(corpus/"benchmark_manifest.json")

def test_should_clarify_no_target_and_acceptable_set_persistence(setup):
    db,_,service,did=setup
    clarify=new_case(service,did,expected_behavior="should_clarify",expected_section_path=None,acceptable_section_paths=["A > X","B > X"])
    no_target=new_case(service,did,expected_behavior="no_target",expected_section_path=None,must_not_target=["Related > Recovery"])
    acceptable=new_case(service,did,expected_behavior="acceptable_set",expected_section_path=None,acceptable_section_paths=["A","B"])
    assert db.decode_case(db.one("SELECT * FROM cases WHERE id=?",(clarify,)))["expected_behavior"]=="should_clarify"
    assert db.decode_case(db.one("SELECT * FROM cases WHERE id=?",(no_target,)))["must_not_target"]==["Related > Recovery"]
    assert db.decode_case(db.one("SELECT * FROM cases WHERE id=?",(acceptable,)))["acceptable_section_paths"]==["A","B"]

def test_response_persistence_and_manual_adjudication(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did)); assert run["textual_response"]=="March 20"
    assert service.adjudicate(run["id"],"pass",None,"Clarified appropriately")["verdict"]=="pass"

def test_taxonomy_and_fail_requirement(setup):
    db,_,service,did=setup; names={r["name"] for r in db.all("SELECT name FROM failure_categories WHERE active=1")}
    assert names==set(DEFAULT_TAXONOMY); run=service.run_case(new_case(service,did))
    with pytest.raises(ValueError,match="required"): service.adjudicate(run["id"],"fail",None,None)

def test_integrity_blocks_run_after_stored_bytes_change(tmp_path):
    db=Database(str(tmp_path/"corpus.db")); service=BenchmarkService(db,FakeSuperDocsClient()); service.import_corpus(MANIFEST)
    case=db.one("SELECT id,document_id FROM cases WHERE external_case_id='D01-C01'")
    db.execute("UPDATE documents SET content=? WHERE id=?",(b"tampered",case["document_id"]))
    with pytest.raises(ValueError,match="frozen fixture changed"): service.run_case(case["id"])

def test_explicit_batch_selection_and_confirmation(setup):
    _,_,service,did=setup; ids=[new_case(service,did,external_case_id=f"T-{i}") for i in range(3)]
    preview=service.batch_preview([ids[2],ids[0]],2,2); assert preview["selected_case_ids"]==["T-2","T-0"]
    with pytest.raises(ValueError,match="confirmation"): service.run_batch([ids[2],ids[0]],2,2,False)
    result=service.run_batch([ids[2],ids[0]],2,2,True); assert [r["case_id"] for r in result["runs"]]==[ids[2],ids[0]]
    with pytest.raises(ValueError,match="maximum requests"): service.batch_preview(ids,2,2)

def test_metrics_difficulty_capability_latency_and_operations(setup):
    db,_,service,did=setup
    a=service.run_case(new_case(service,did,difficulty="hard",capability_tested="ordinal",external_case_id="O-1")); b=service.run_case(new_case(service,did,"edit",difficulty="easy",capability_tested="baseline",external_case_id="O-2"))
    category=db.one("SELECT id FROM failure_categories WHERE name='wrong_duplicate'")["id"]
    service.adjudicate(a["id"],"pass",None,None); service.adjudicate(b["id"],"fail",category,None); m=service.metrics()
    assert m["evaluated"]==2 and m["pass_rate"]==.5 and m["total_operations_charged"]==2
    assert {r["difficulty"] for r in m["by_difficulty"]}=={"easy","hard"}
    assert {r["capability_tested"] for r in m["by_capability"]}=={"baseline","ordinal"}
    assert m["p50_latency_ms"]>0 and m["p95_latency_ms"]>=m["p50_latency_ms"]

def test_official_results_exclude_custom_experiments(setup):
    _,_,service,did=setup
    official=service.run_case(new_case(service,did,external_case_id="OFFICIAL-1"))
    custom=service.run_case(new_case(service,did))
    service.adjudicate(official["id"],"pass",None,None)
    service.adjudicate(custom["id"],"ambiguous",None,"Not enough evidence")
    metrics=service.metrics()
    assert metrics["official_cases"]==1 and metrics["custom_cases"]==1
    assert metrics["evaluated"]==1 and metrics["pass"]==1 and metrics["ambiguous"]==0

def test_taxonomy_definitions_and_case_scope_api(tmp_path):
    app=create_app(Settings(db_path=str(tmp_path/"api.db"),client_mode="fake"),FakeSuperDocsClient())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            await client.post("/api/corpus/import")
            frozen=(await client.get("/api/cases?scope=frozen")).json()
            custom=(await client.get("/api/cases?scope=custom")).json()
            definitions=(await client.get("/api/taxonomy/definitions")).json()
            assert len(frozen)==40 and custom==[]
            assert {case["external_case_id"] for case in frozen}.isdisjoint({"D06-C02","D08-C02"})
            assert definitions and all(x["name"] and x["definition"] for x in definitions)
    asyncio.run(scenario())

def test_api_import_filters_and_batch_preview(tmp_path):
    app=create_app(Settings(db_path=str(tmp_path/"api.db"),client_mode="fake"),FakeSuperDocsClient())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            imported=await client.post("/api/corpus/import"); assert imported.json()["cases_total"]==40
            rows=(await client.get("/api/cases?difficulty=adversarial&expected_behavior=no_target")).json(); assert rows and all(r["difficulty"]=="adversarial" and r["expected_behavior"]=="no_target" for r in rows)
            selected=(await client.get("/api/cases?case_type=search")).json()[:2]
            body={"case_ids":[selected[1]["id"],selected[0]["id"]],"max_requests":2,"max_operations":2}
            preview=await client.post("/api/runs/batch/preview",json=body); assert preview.status_code==200
            denied=await client.post("/api/runs/batch",json=body); assert denied.status_code==400
            edit=(await client.get("/api/cases?case_type=edit")).json()[0]
            run=await client.post(f"/api/cases/{edit['id']}/run")
            document=await client.get(f"/api/runs/{run.json()['id']}/preview")
            assert document.status_code==200 and document.headers["content-type"].startswith("text/html")
    asyncio.run(scenario())

def test_api_error_is_persisted(setup):
    db,_,_,did=setup; service=BenchmarkService(db,FakeSuperDocsClient(fail=True)); run=service.run_case(new_case(service,did)); assert run["status"]=="error" and run["error"]=="Fake upstream error"

def test_async_edit_exposes_independent_change(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did,"edit")); change=run["evidence"]["pending_changes"][0]
    assert run["status"]=="awaiting_approval" and change["change_id"] and change["chunk_id"] and change["old_html"]!=change["new_html"]

def test_benchmark_run_persists_across_app_restart(tmp_path):
    path=str(tmp_path/"persistent.db")
    first=BenchmarkService(Database(path),FakeSuperDocsClient())
    did=first.create_document({"name":"Projects","filename":"projects.html","content_type":"text/html"},b"<p>March 20</p>")
    attempt=first.run_case(new_case(first,did,external_case_id="PERSIST-1"))
    first.adjudicate(attempt["id"],"pass",None,"saved")
    selected=first.current_benchmark_run()["id"]
    restarted=BenchmarkService(Database(path),FakeSuperDocsClient())
    assert restarted.current_benchmark_run()["id"]==selected
    assert restarted.get_run(attempt["id"])["verdict"]=="pass"
    assert restarted.metrics()["pass"]==1

def test_fresh_benchmark_run_is_empty_and_preserves_previous_run(setup):
    _,_,service,did=setup
    first_id=service.current_benchmark_run()["id"]
    attempt=service.run_case(new_case(service,did,external_case_id="FRESH-1"))
    service.adjudicate(attempt["id"],"pass",None,None)
    fresh=service.start_benchmark_run()
    assert fresh["id"]!=first_id and service.metrics()["evaluated"]==0
    assert service.get_run(attempt["id"])["verdict"]=="pass"
    service.select_benchmark_run(first_id)
    assert service.metrics()["pass"]==1

def test_run_again_creates_new_unreviewed_attempt_without_overwrite(setup):
    db,_,service,did=setup
    cid=new_case(service,did,external_case_id="RETRY-1")
    first=service.run_case(cid); service.adjudicate(first["id"],"fail",db.one("SELECT id FROM failure_categories WHERE name='other'")["id"],"first attempt")
    second=service.run_case(cid)
    assert second["id"]!=first["id"] and second["verdict"] is None
    assert service.get_run(first["id"])["verdict"]=="fail"
    assert db.one("SELECT COUNT(*) n FROM runs WHERE case_id=?",(cid,))["n"]==2
    metrics=service.metrics()
    assert metrics["evaluated"]==0
    assert metrics["total_operations_charged"]==1

def test_superseded_zero_operation_error_does_not_affect_latest_operations(setup):
    _,_,service,did=setup
    cid=new_case(service,did,external_case_id="ERROR-RETRY-1")
    service.client=FakeSuperDocsClient(fail=True)
    failed=service.run_case(cid)
    assert failed["status"]=="error" and failed["operations_charged"]==0
    service.client=FakeSuperDocsClient()
    successful=service.run_case(cid)
    assert successful["operations_charged"]==1
    assert service.metrics()["total_operations_charged"]==1

def test_metrics_are_scoped_to_selected_benchmark_run(setup):
    _,_,service,did=setup
    cid=new_case(service,did,external_case_id="SCOPED-1")
    old_id=service.current_benchmark_run()["id"]
    old_attempt=service.run_case(cid); service.adjudicate(old_attempt["id"],"pass",None,None)
    new_id=service.start_benchmark_run()["id"]
    new_attempt=service.run_case(cid); service.adjudicate(new_attempt["id"],"ambiguous",None,None)
    assert service.metrics(benchmark_run_id=old_id)["pass"]==1
    current=service.metrics(benchmark_run_id=new_id)
    assert current["pass"]==0 and current["ambiguous"]==1

def test_chunk_ids_resolve_to_parent_heading_paths():
    html="""<h1 data-chunk-id="p">2. User Experience</h1>
      <h2 data-chunk-id="h">2.2 Empty and Error States</h2>
      <p data-chunk-id="body">The interface explains missing team scope.</p>"""
    mapping=build_chunk_heading_map(html)
    assert mapping["body"]=="2. User Experience > 2.2 Empty and Error States"

def test_repeated_identical_headings_resolve_under_distinct_parents():
    html="""<h1 data-chunk-id="a">Web Application</h1><h2 data-chunk-id="a-roll">Rollback Plan</h2><p data-chunk-id="a-body">Web rollback.</p>
      <h1 data-chunk-id="b">Mobile Applications</h1><div data-chunk-id="b-wrap"><h2>Rollback Plan</h2><p>Mobile rollback.</p></div><p data-chunk-id="b-body">Already-installed binaries cannot be recalled.</p>"""
    mapping=build_chunk_heading_map(html)
    assert mapping["a-roll"]=="Web Application > Rollback Plan"
    assert mapping["b-wrap"]=="Mobile Applications > Rollback Plan"
    assert mapping["b-body"]=="Mobile Applications > Rollback Plan"

def test_docx_heading_styles_resolve_repeated_paragraph_heading_chunks():
    source=(ROOT/"outputs"/"benchmark_corpus"/"documents"/"D02_Software_Release_Plan.docx").read_bytes()
    html=''.join(f'<p data-chunk-id="rollback-{index}">Rollback Plan</p>' for index in range(3))
    mapping=build_chunk_heading_map(html,source,"D02_Software_Release_Plan.docx")
    assert mapping=={
        "rollback-0":"Web Application > Rollback Plan",
        "rollback-1":"Mobile Applications > Rollback Plan",
        "rollback-2":"Platform Services > Rollback Plan",
    }

def test_create_change_resolves_using_insert_after_chunk_id():
    changes=resolve_pending_changes([{"change_id":"new","operation":"create","chunk_id":"new","insert_after_chunk_id":"anchor"}],{"anchor":"Launch > Rollout Plan"})
    assert changes[0]["resolved_section_path"]=="Launch > Rollout Plan"

def test_unresolved_chunk_path_is_not_guessed():
    changes=resolve_pending_changes([{"change_id":"x","operation":"edit","chunk_id":"missing"}],{})
    assert changes[0]["resolved_section_path"] is None

def test_awaiting_approval_uses_current_document_label():
    script=(ROOT/"app"/"static"/"app.js").read_text()
    assert "r.status==='awaiting_approval'" in script
    assert "View current document" in script
