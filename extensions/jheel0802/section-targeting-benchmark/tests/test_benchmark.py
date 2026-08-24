import asyncio
import base64
import csv
import hashlib
import itertools
import json
import re
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.db import DEFAULT_TAXONOMY, Database, now
from app.main import create_app
from app.service import BenchmarkService
from app.superdocs import FakeSuperDocsClient, RealSuperDocsClient, build_chunk_heading_map, resolve_pending_changes
from app.document_evidence import diff_documents, parse_document_html, render_annotated_document
from app.targeting import PUBLIC_FAILURE_DEFINITIONS, REVIEWED_STRICT_FAILURES, assess_targeting, verdict_summary
from app.public_snapshot import PRIVATE_KEYS, import_public_snapshot

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"outputs"/"benchmark_corpus"/"benchmark_manifest.json"
PUBLIC_SNAPSHOT=ROOT/"outputs"/"final_run"/"public_snapshot.json"

@pytest.fixture
def setup(tmp_path):
    db=Database(str(tmp_path/"test.db")); fake=FakeSuperDocsClient(); service=BenchmarkService(db,fake,5,5)
    document_id=add_test_document(db,b"<h1>Projects</h1><p>March 20</p>")
    return db,fake,service,document_id

TEST_CASE_SEQUENCE=itertools.count(1)

def add_test_document(db,content=b"<p>source</p>",filename="projects.html"):
    digest=hashlib.sha256(content).hexdigest()
    return db.execute("INSERT INTO documents(name,filename,content_type,content,actual_sha256,created_at) VALUES (?,?,?,?,?,?)",("Projects",filename,"text/html",content,digest,now()))

def new_case(service,document_id,case_type="search",**overrides):
    payload={"title":"Target timeline","case_type":case_type,"document_id":document_id,"instruction":"What is the deadline?" if case_type=="search" else "Change the deadline.","expected_behavior":"unique_target","expected_section_path":"Projects > X > Timeline","expected_answer":"March 20","acceptable_section_paths":[],"must_not_target":["Projects > Y > Timeline"],"external_case_id":f"TEST-{next(TEST_CASE_SEQUENCE)}"}
    payload.update(overrides)
    case_id=service.db.execute("""INSERT INTO cases(title,case_type,document_id,instruction,expected_section,expected_answer,notes,external_case_id,difficulty,expected_behavior,expected_section_path,acceptable_section_paths_json,expected_edit_scope,must_not_target_json,capability_tested,likely_failure_category,rationale,fixture_version,expected_document_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
      payload["title"],payload["case_type"],payload["document_id"],payload["instruction"],payload.get("expected_section_path") or "",payload.get("expected_answer"),payload.get("notes"),payload["external_case_id"],payload.get("difficulty"),payload["expected_behavior"],payload.get("expected_section_path"),json.dumps(payload.get("acceptable_section_paths") or []),payload.get("expected_edit_scope"),json.dumps(payload.get("must_not_target") or []),payload.get("capability_tested"),payload.get("likely_failure_category"),payload.get("rationale"),payload.get("fixture_version"),payload.get("expected_document_sha256"),now()))
    benchmark_run_id=service.current_benchmark_run()["id"]
    service.db.execute("INSERT INTO benchmark_run_cases(benchmark_run_id,case_id) VALUES (?,?)",(benchmark_run_id,case_id))
    service.db.execute("UPDATE benchmark_runs SET corpus_case_total=corpus_case_total+1 WHERE id=?",(benchmark_run_id,))
    return case_id

def test_case_creation_preserves_structured_fields(setup):
    db,_,service,did=setup; cid=new_case(service,did,external_case_id="X-C01",difficulty="hard",capability_tested="parent_context",expected_edit_scope="one section")
    case=db.decode_case(db.one("SELECT * FROM cases WHERE id=?",(cid,)))
    assert case["external_case_id"]=="X-C01" and case["difficulty"]=="hard"
    assert case["must_not_target"]==["Projects > Y > Timeline"] and case["acceptable_section_paths"]==[]

def test_manifest_import_all_fields_and_idempotency(tmp_path):
    db=Database(str(tmp_path/"corpus.db")); service=BenchmarkService(db,FakeSuperDocsClient())
    first=service.import_corpus(MANIFEST); second=service.import_corpus(MANIFEST)
    assert (first["documents_created"],first["cases_created"])==(14,60)
    assert (second["documents_created"],second["cases_created"])==(0,0)
    case=db.decode_case(db.one("SELECT * FROM cases WHERE external_case_id='D09-C01'"))
    source=next(c for c in json.loads(MANIFEST.read_text())["cases"] if c["case_id"]=="D09-C01")
    assert case["expected_behavior"]=="should_clarify"
    assert case["acceptable_section_paths"]==source["acceptable_section_paths"]
    assert case["must_not_target"]==source["must_not_target"]
    assert case["fixture_version"]==source["fixture_version"]
    assert case["expected_document_sha256"]==source["document_sha256"]

def test_corpus_version_snapshots_preserve_historical_40_case_runs(tmp_path):
    db=Database(str(tmp_path/"versioned.db")); service=BenchmarkService(db,FakeSuperDocsClient()); service.import_corpus(MANIFEST)
    historical=service.current_benchmark_run()["id"]
    db.execute("""DELETE FROM benchmark_run_cases WHERE benchmark_run_id=? AND case_id IN
      (SELECT id FROM cases WHERE external_case_id GLOB 'D??-C0[4-5]')""",(historical,))
    db.execute("UPDATE benchmark_runs SET corpus_version='1.0.1',corpus_case_total=40 WHERE id=?",(historical,))
    service.import_corpus(MANIFEST)
    old=next(r for r in service.list_benchmark_runs() if r["id"]==historical)
    assert old["corpus_version"]=="1.0.1" and old["official_cases_total"]==40
    assert service.metrics(benchmark_run_id=historical)["official_cases"]==40
    fresh=service.start_benchmark_run()
    assert fresh["corpus_version"]=="1.1.0" and fresh["corpus_case_total"]==60
    assert service.metrics(benchmark_run_id=fresh["id"])["official_cases"]==60

def test_expanded_manifest_contains_20_single_target_additions():
    data=json.loads(MANIFEST.read_text()); additions={c["case_id"]:c for c in data["cases"] if c["case_id"][-2:] in {"04","05"}}
    assert data["corpus_version"]=="1.1.0" and data["case_count"]==60 and len(additions)==20
    assert additions["D01-C04"]["expected_section_path"]=="Harbor Retail > Timeline"
    assert additions["D08-C05"]["expected_section_path"]=="Appendix > Dependency Register"
    assert additions["D09-C04"]["expected_section_path"]=="3. United Kingdom Employees > 3.1 Time Off"
    assert additions["D12-C05"]["expected_section_path"]=="Appendix B > Management Action Summary"
    assert all(c["expected_behavior"]!="acceptable_set" for c in additions.values())
    with (MANIFEST.parent/"benchmark_manifest.csv").open(newline="") as handle:
        assert len(list(csv.DictReader(handle)))==60

def test_public_snapshot_bootstraps_latest_experiment_and_fresh_run_is_isolated(tmp_path):
    db=Database(str(tmp_path/"published.db")); fake=FakeSuperDocsClient(); service=BenchmarkService(db,fake,60,60)
    service.import_corpus(MANIFEST)
    imported=import_public_snapshot(db,PUBLIC_SNAPSHOT)
    assert imported["attempts"]==61
    published=service.current_benchmark_run()
    assert published["name"]=="Published Benchmark run 4" and published["read_only"]==1
    assert len(service.list_benchmark_runs())==1
    metrics=service.metrics()
    assert (metrics["official_cases"],metrics["official_cases_run"],metrics["pass"],metrics["fail"],metrics["total_operations_charged"])==(60,60,56,4,38)
    assert metrics["applied_verification"]=={"verified":15,"landed_in_intended_section":13,"did_not_land_correctly":0,"cannot_determine":2,"unrelated_changes_detected":0}
    assert metrics["guided_recovery"]["cases_recovered"]==2
    case_id=db.one("SELECT id FROM cases WHERE external_case_id='D01-C01'")["id"]
    with pytest.raises(ValueError,match="read-only"): service.run_case(case_id,published["id"])
    assert fake.jobs=={}
    fresh=service.start_benchmark_run()
    assert fresh["read_only"]==0 and service.metrics()["official_cases_run"]==0
    assert service.metrics(published["id"])["pass"]==56

def test_public_snapshot_contains_no_remote_or_account_identifiers():
    payload=json.loads(PUBLIC_SNAPSHOT.read_text()); hits=[]
    def inspect(value,path="root"):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in PRIVATE_KEYS or (key.lower().endswith("_id") and key.lower() not in {"external_case_id","chunk_id","change_id","insert_after_chunk_id","insert_before_chunk_id"}): hits.append(path+"."+key)
                inspect(item,path+"."+key)
        elif isinstance(value,list):
            for index,item in enumerate(value): inspect(item,f"{path}[{index}]")
        elif isinstance(value,str) and value[:1] in "[{":
            try: inspect(json.loads(value),path+"<json>")
            except json.JSONDecodeError: pass
    inspect(payload)
    assert hits==[]
    assert re.search(r"sk-[A-Za-z0-9_-]{20,}",PUBLIC_SNAPSHOT.read_text()) is None

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

def test_new_taxonomy_is_simple_and_old_categories_are_display_converted(setup):
    db,_,service,did=setup
    assert {r["name"] for r in db.all("SELECT name FROM failure_categories WHERE active=1")}=={
        "wrong_target","should_have_clarified","unsupported_target","right_target_wrong_result","other"
    }
    old_id=db.one("SELECT id FROM failure_categories WHERE name='correct_section_wrong_answer'")["id"]
    run=service.run_case(new_case(service,did,external_case_id="HISTORICAL-DISPLAY"))
    db.execute("UPDATE runs SET verdict='fail',failure_category_id=? WHERE id=?",(old_id,run["id"]))
    assert service.get_run(run["id"])["failure_category"]=="Right target, wrong result"

def test_new_failure_category_drives_targeting_without_case_id_history(setup):
    db,_,service,did=setup
    category=db.one("SELECT id FROM failure_categories WHERE name='wrong_target'")["id"]
    run=service.run_case(new_case(service,did,external_case_id="D02-C01"))
    service.adjudicate(run["id"],"fail",category,None)
    metrics=service.metrics()
    assert metrics["targeting"]=={"total":1,"pass":0,"fail":1,"cannot_determine":0,"accuracy":0}
    assert metrics["by_failure_category"][0]["name"]=="Wrong target"

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

def test_select_all_uses_currently_filtered_cases():
    script=(ROOT/"app"/"static"/"app.js").read_text()
    assert "Select all shown" in script
    assert "const rows=filteredCaseRows()" in script
    assert "new Set(rows.map(c=>c.id))" in script
    assert "keepOnlyVisibleSelections()" in script
    assert "filter(id=>visible.has(id))" in script
    assert "updateQuickFilterHighlight()" in script
    assert 'app.js?v=7' in (ROOT/"app"/"static"/"index.html").read_text()

def test_metrics_difficulty_capability_latency_and_operations(setup):
    db,_,service,did=setup
    a=service.run_case(new_case(service,did,difficulty="hard",capability_tested="ordinal",external_case_id="O-1")); b=service.run_case(new_case(service,did,"edit",difficulty="easy",capability_tested="baseline",external_case_id="O-2"))
    category=db.one("SELECT id FROM failure_categories WHERE name='wrong_target'")["id"]
    service.adjudicate(a["id"],"pass",None,None); service.adjudicate(b["id"],"fail",category,None); m=service.metrics()
    assert m["evaluated"]==2 and m["pass_rate"]==.5 and m["total_operations_charged"]==2
    assert {r["difficulty"] for r in m["by_difficulty"]}=={"easy","hard"}
    assert {r["capability_tested"] for r in m["by_capability"]}=={"baseline","ordinal"}
    assert m["p50_latency_ms"]>0 and m["p95_latency_ms"]>=m["p50_latency_ms"]

def test_taxonomy_definitions_and_official_cases_api(tmp_path):
    app=create_app(Settings(db_path=str(tmp_path/"api.db"),client_mode="fake"),FakeSuperDocsClient())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            await client.post("/api/corpus/import")
            frozen=(await client.get("/api/cases")).json()
            definitions=(await client.get("/api/taxonomy/definitions")).json()
            assert len(frozen)==60
            assert {case["external_case_id"] for case in frozen}.isdisjoint({"D06-C02","D08-C02"})
            assert definitions and all(x["name"] and x["definition"] for x in definitions)
            assert (await client.post("/api/cases",json={})).status_code==405
            assert (await client.post("/api/documents",json={})).status_code==405
            assert (await client.get("/api/config")).json()["default_manifest"]=="outputs/benchmark_corpus/benchmark_manifest.json"
    asyncio.run(scenario())

def test_api_import_filters_and_batch_preview(tmp_path):
    app=create_app(Settings(db_path=str(tmp_path/"api.db"),client_mode="fake"),FakeSuperDocsClient())
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            imported=await client.post("/api/corpus/import"); assert imported.json()["cases_total"]==60
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
    did=add_test_document(first.db,b"<p>March 20</p>")
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
    assert "Approve test edit" in script
    assert "Before approval" in script and "After approval" in script

def test_complete_nested_paths_and_expected_section_range():
    html='''<h1 data-chunk-id="a">Europe</h1><p data-chunk-id="a0">Overview</p>
      <h2 data-chunk-id="b">Pipeline</h2><p data-chunk-id="b1">Coverage</p><p data-chunk-id="b2">Owner</p>
      <h2 data-chunk-id="c">Risks</h2><p data-chunk-id="c1">Risk</p>'''
    structure=parse_document_html(html)
    assert structure.chunk_paths["b1"]=="Europe > Pipeline"
    assert structure.path_chunks["Europe > Pipeline"]==["b","b1","b2"]

def test_expected_ranges_distinguish_duplicate_headings_by_parent():
    html='''<h1 data-chunk-id="a">Project A</h1><h2 data-chunk-id="at">Timeline</h2><p data-chunk-id="ab">June</p>
      <h1 data-chunk-id="b">Project B</h1><h2 data-chunk-id="bt">Timeline</h2><p data-chunk-id="bb">July</p>'''
    structure=parse_document_html(html)
    assert structure.path_chunks["Project A > Timeline"]==["at","ab"]
    assert structure.path_chunks["Project B > Timeline"]==["bt","bb"]

def test_viewer_sanitizes_active_content_and_highlights_exact_chunk():
    html='''<h1 data-chunk-id="h">Projects</h1><p data-chunk-id="target" onclick="steal()">Text</p>
      <script>alert(1)</script><form><input></form><iframe src="https://bad.test"></iframe><object></object><embed>'''
    rendered=render_annotated_document(html,"Projects",["target"],[])
    assert "benchmark-proposed" in rendered and 'data-chunk-id="target"' in rendered
    assert "onclick" not in rendered and "<script" not in rendered and "<form" not in rendered
    assert "<iframe" not in rendered and "<object" not in rendered and "<embed" not in rendered
    assert "Content-Security-Policy" in rendered

def test_missing_create_placement_is_explicitly_unavailable():
    change=resolve_pending_changes([{"change_id":"x","operation":"create","chunk_id":"new"}],{})[0]
    assert change["resolved_section_path"] is None
    assert change["proposal_placement_unavailable"] is True
    assert "Proposal placement unavailable" in (ROOT/"app"/"static"/"app.js").read_text()

def test_applied_edit_diff_and_unrelated_change_detection():
    before='<h1 data-chunk-id="h">Title</h1><p data-chunk-id="a">Old</p><p data-chunk-id="other">Same</p>'
    after='<h1 data-chunk-id="h">Title</h1><p data-chunk-id="a">New</p><p data-chunk-id="other">Changed too</p>'
    result=diff_documents(before,after,[{"operation":"edit","chunk_id":"a"}])
    assert result["changed_chunk_ids"]==["a","other"]
    assert result["unrelated_chunk_ids"]==["other"] and result["unrelated_changes_detected"]

def test_applied_create_diff_detects_new_chunk():
    before='<h1 data-chunk-id="h">Title</h1><p data-chunk-id="a">Old</p>'
    after=before+'<p data-chunk-id="new-1">Added</p>'
    result=diff_documents(before,after,[{"operation":"create","chunk_id":"new","insert_after_chunk_id":"a"}])
    assert result["new_chunk_ids"]==["new-1"] and result["deleted_chunk_ids"]==[]
    assert result["create_placements"][0]["placement_verified"] is True

def test_applied_delete_diff_detects_removed_chunk():
    before='<h1 data-chunk-id="h">Title</h1><p data-chunk-id="gone">Remove</p>'
    after='<h1 data-chunk-id="h">Title</h1>'
    result=diff_documents(before,after,[{"operation":"delete","chunk_id":"gone"}])
    assert result["deleted_chunk_ids"]==["gone"] and not result["unrelated_changes_detected"]

def test_stored_html_viewer_makes_no_superdocs_call(setup):
    _,fake,service,did=setup
    run=service.run_case(new_case(service,did,"edit"))
    calls=len(fake.approval_calls)
    viewer=service.viewer_html(run["id"])
    assert "data-chunk-id" in viewer and len(fake.approval_calls)==calls

def test_approval_persists_applied_evidence_and_preserves_original_verdict(tmp_path):
    path=str(tmp_path/"approval.db"); db=Database(path)
    fake=FakeSuperDocsClient(post_approval_html='<h1 data-chunk-id="h1">Projects</h1><p data-chunk-id="observed-chunk-1">Deadline: March 27.</p>')
    service=BenchmarkService(db,fake); did=add_test_document(db,b"<p>source</p>")
    run=service.run_case(new_case(service,did,"edit",external_case_id="APPROVE-1")); service.adjudicate(run["id"],"pass",None,"original")
    applied=service.approve_test_edit(run["id"])
    assert fake.approval_calls[0]["approved"] is True
    assert applied["approval_status"]=="completed" and applied["changed_chunk_ids"]==["observed-chunk-1"]
    service.save_applied_verification(run["id"],True,True,"landed correctly")
    assert service.get_run(run["id"])["verdict"]=="pass"
    restarted=BenchmarkService(Database(path),FakeSuperDocsClient())
    persisted=restarted.get_applied_verification(run["id"])
    assert persisted["post_approval_html"] and persisted["applied_target_correct"] is True
    assert persisted["applied_verification_notes"]=="landed correctly"
    assert restarted.get_run(run["id"])["adjudication_note"]=="original"

def test_duplicate_approval_is_idempotent(setup):
    _,fake,service,did=setup; run=service.run_case(new_case(service,did,"edit"))
    service.approve_test_edit(run["id"]); again=service.approve_test_edit(run["id"])
    assert again["duplicate_approval_prevented"] is True and len(fake.approval_calls)==1

def test_second_proposal_batch_pauses_for_explicit_approval(setup):
    _,_,service,did=setup
    second={"change_id":"change-2","operation":"edit","chunk_id":"observed-chunk-1","document_id":"doc_primary","old_html":"old","new_html":"new"}
    fake=FakeSuperDocsClient(approval_jobs=[{"status":"awaiting_approval","metadata":{"awaiting_kind":"change_review","pending_changes":[second]}}])
    service.client=fake; run=service.run_case(new_case(service,did,"edit")); applied=service.approve_test_edit(run["id"])
    assert applied["approval_status"]=="additional_approval_required"
    assert applied["pending_changes"][0]["change_id"]=="change-2" and len(fake.approval_calls)==1

def test_continue_prompt_cannot_use_change_approval(setup):
    db,_,service,did=setup; run=service.run_case(new_case(service,did,"edit"))
    raw=run["raw_response"]; raw["job"]["metadata"]["awaiting_kind"]="continue_prompt"
    db.execute("UPDATE runs SET raw_response_json=? WHERE id=?",(json.dumps(raw),run["id"]))
    with pytest.raises(ValueError,match="continuation"): service.approve_test_edit(run["id"])

def test_approval_rejected_for_non_edit_case(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did,"search"))
    with pytest.raises(ValueError,match="edit cases"): service.approve_test_edit(run["id"])

def test_viewer_endpoint_is_sandboxed_and_does_not_export(tmp_path):
    fake=FakeSuperDocsClient(); app=create_app(Settings(db_path=str(tmp_path/"viewer.db"),client_mode="fake"),fake)
    service=app.state.service; did=add_test_document(app.state.db,b"x","x.html")
    run=service.run_case(new_case(service,did,"edit"))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
            response=await client.get(f"/api/runs/{run['id']}/viewer")
            assert response.status_code==200 and "default-src 'none'" in response.headers["content-security-policy"]
    asyncio.run(scenario())
    script=(ROOT/"app"/"static"/"app.js").read_text()
    assert 'id="document-viewer"' in script and "sandbox src=" in script
    assert "allow-scripts" not in script and "allow-same-origin" not in script

def test_post_approval_selects_pending_change_document(setup):
    class MultiDocumentFake(FakeSuperDocsClient):
        def list_session_documents(self,session_id):
            return {"documents":[
                {"document_id":"other","html":'<p data-chunk-id="wrong">Wrong document</p>'},
                {"document_id":"doc_primary","html":self.post_approval_html},
            ]}
    _,_,service,did=setup
    fake=MultiDocumentFake(); service.client=fake
    run=service.run_case(new_case(service,did,"edit")); applied=service.approve_test_edit(run["id"])
    assert applied["session_document_id"]=="doc_primary"
    assert "observed-chunk-1" in applied["post_approval_html"] and "Wrong document" not in applied["post_approval_html"]

def test_real_approval_payload_has_required_top_level_approved():
    client=RealSuperDocsClient(Settings(api_key="test-only")); captured={}
    client._json=lambda method,path,**kwargs: captured.update({"method":method,"path":path,**kwargs}) or {"status":"processing"}
    client.decide_changes("session","job",[{"change_id":"c1","approved":True}])
    assert captured["json"]["job_id"]=="job" and captured["json"]["approved"] is True
    assert captured["json"]["changes"][0]["approved"] is True

def test_real_client_fetches_updated_session_html():
    client=RealSuperDocsClient(Settings(api_key="test-only")); captured={}
    client._json=lambda method,path,**kwargs: captured.update({"method":method,"path":path,**kwargs}) or {"documents":[]}
    client.list_session_documents("session-1")
    assert captured=={"method":"GET","path":"/v1/sessions/session-1/documents","params":{"include_html":"true"}}

def test_real_rejection_payload_uses_feedback_in_same_session():
    client=RealSuperDocsClient(Settings(api_key="test-only")); calls=[]
    client._json=lambda method,path,**kwargs: calls.append({"method":method,"path":path,**kwargs}) or {"status":"processing"}
    client.decide_changes("same-session","old-job",[{"change_id":"c1","approved":False,"feedback":"Use Section B"}])
    assert calls[0]["path"]=="/v1/chat/same-session/approve"
    assert calls[0]["json"]=={"job_id":"old-job","approved":False,"changes":[{"change_id":"c1","approved":False,"feedback":"Use Section B"}]}
    assert len(calls)==1

def test_guided_recovery_requires_pending_edit_and_guidance(setup):
    _,_,service,did=setup
    search=service.run_case(new_case(service,did,"search"))
    with pytest.raises(ValueError,match="pending edit"): service.start_guided_recovery(search["id"],"Use X")
    edit=service.run_case(new_case(service,did,"edit"))
    with pytest.raises(ValueError,match="guidance is required"): service.start_guided_recovery(edit["id"],"  ")
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "case_type==='edit'" in script and "status==='awaiting_approval'" in script

def test_guided_recovery_is_separate_idempotent_and_persistent(tmp_path):
    path=str(tmp_path/"recovery.db"); db=Database(path); fake=FakeSuperDocsClient(); service=BenchmarkService(db,fake)
    did=add_test_document(db,b"x","x.html")
    run=service.run_case(new_case(service,did,"edit",external_case_id="RECOVERY-1"))
    category=db.one("SELECT id FROM failure_categories WHERE name='wrong_target'")["id"]
    service.adjudicate(run["id"],"fail",category,"original failure")
    original=json.dumps(service.get_run(run["id"])["evidence"]["pending_changes"],sort_keys=True)
    recovery=service.start_guided_recovery(run["id"],"Use Projects only")
    assert fake.approval_calls[0]["approved"] is False and fake.approval_calls[0]["changes"][0]["feedback"]=="Use Projects only"
    assert fake.followup_calls==[]
    assert recovery["recovery_job_id"]==run["job_id"] and recovery["recovery_target_path"]=="Projects"
    assert json.dumps(service.get_run(run["id"])["evidence"]["pending_changes"],sort_keys=True)==original
    duplicate=service.start_guided_recovery(run["id"],"Try a second time")
    assert duplicate["duplicate_submit_prevented"] and len(fake.approval_calls)==1 and len(fake.followup_calls)==0
    service.adjudicate_guided_recovery(run["id"],"recovered","correct now")
    assert service.get_run(run["id"])["verdict"]=="fail" and service.get_run(run["id"])["adjudication_note"]=="original failure"
    restarted=BenchmarkService(Database(path),FakeSuperDocsClient())
    assert restarted.get_guided_recovery(run["id"])["recovery_verdict"]=="recovered"
    assert restarted.viewer_html(run["id"],"recovery").find("benchmark-proposed")!=-1

def test_recovery_operations_are_excluded_from_official_metrics(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did,"edit",external_case_id="RECOVERY-OPS"))
    service.start_guided_recovery(run["id"],"Use Projects")
    assert service.metrics()["total_operations_charged"]==1
    summary=service.guided_recovery_summary()
    assert summary["cases_attempted"]==1 and summary["cases_recovered"]==0
    assert summary["awaiting_evaluation"]==1 and summary["additional_api_operations"]==1
    assert service.metrics()["guided_recovery"]==summary

def test_recovery_verdict_validation_cannot_touch_original(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did,"edit")); service.start_guided_recovery(run["id"],"Use Projects")
    with pytest.raises(ValueError,match="invalid recovery"): service.adjudicate_guided_recovery(run["id"],"pass")
    assert service.get_run(run["id"])["verdict"] is None

def test_guided_recovery_api_failure_is_persisted_and_duplicate_safe(setup):
    class RejectFailure(FakeSuperDocsClient):
        def decide_changes(self,*args,**kwargs):
            self.approval_calls.append({"failed":True}); raise RuntimeError("reject unavailable")
    _,_,service,did=setup; fake=RejectFailure(); service.client=fake
    run=service.run_case(new_case(service,did,"edit"))
    with pytest.raises(RuntimeError,match="reject unavailable"): service.start_guided_recovery(run["id"],"Use Projects")
    saved=service.get_guided_recovery(run["id"])
    assert saved["recovery_status"]=="error" and "reject unavailable" in saved["error"]
    again=service.start_guided_recovery(run["id"],"Use Projects")
    assert again["duplicate_submit_prevented"] and len(fake.approval_calls)==1

def test_guided_recovery_ui_preserves_original_and_requires_explicit_submit():
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "Reject and guide" in script and "Reject proposal and send guidance" in script
    assert "This preserves the original failed proposal" in script
    assert "if(!guidance)" in script
    assert "baseViewRun" in script and "recovery_pending_changes" in script

def test_rejection_feedback_recovery_does_not_send_redundant_chat(setup):
    _,fake,service,did=setup; run=service.run_case(new_case(service,did,"edit"))
    recovery=service.start_guided_recovery(run["id"],"Use the intended section")
    assert recovery["recovery_status"]=="awaiting_approval"
    assert recovery["recovery_pending_changes"][0]["change_id"]=="recovery-change-1"
    assert fake.followup_calls==[]

def test_saved_session_busy_record_repairs_from_stored_revised_batch(setup):
    db,_,service,did=setup; run=service.run_case(new_case(service,did,"edit"))
    original=(run["evidence"]["pending_changes"]); revised={"change_id":"revised","operation":"edit","chunk_id":"observed-chunk-1","old_html":"old","new_html":"new"}
    stamp="2026-08-22T00:00:00+00:00"; rejection={"decision":{"status":"ok"},"job":{"job_id":run["job_id"],"status":"awaiting_approval","metadata":{"pending_changes":[revised]}}}
    db.execute("""INSERT INTO guided_recoveries(original_run_id,original_change_ids_json,original_pending_changes_json,original_target_path,guidance_text,recovery_session_id,recovery_status,recovery_raw_response_json,error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
      (run["id"],json.dumps(["change-1"]),json.dumps(original),"Projects","Use Projects",run["session_id"],"error",json.dumps({"rejection":rejection}),"session_busy",stamp,stamp))
    repaired=service.get_guided_recovery(run["id"])
    assert repaired["recovery_status"]=="awaiting_approval" and repaired["error"] is None
    assert repaired["recovery_target_path"]=="Projects" and repaired["recovery_pending_changes"][0]["change_id"]=="revised"

def test_guided_recovery_dashboard_metrics_are_run_scoped(setup):
    _,_,service,did=setup; first_run=service.current_benchmark_run()["id"]
    attempt=service.run_case(new_case(service,did,"edit",external_case_id="RECOVERY-SCOPE"))
    service.start_guided_recovery(attempt["id"],"Use Projects")
    service.adjudicate_guided_recovery(attempt["id"],"recovered")
    first=service.metrics(benchmark_run_id=first_run)["guided_recovery"]
    assert first["cases_attempted"]==1 and first["cases_recovered"]==1 and first["recovery_rate"]==1
    fresh=service.start_benchmark_run()
    empty=service.metrics(benchmark_run_id=fresh["id"])["guided_recovery"]
    assert empty["cases_attempted"]==0 and empty["cases_recovered"]==0 and empty["recovery_rate"] is None

def test_dashboard_labels_guided_recovery_separately():
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "Additional experiments" in script and "Guided recovery" in script
    assert "separate from official benchmark scores" in script
    assert "API-reported operations" in script and "Not reported by API" in script
    assert "new MutationObserver" in script and "document.querySelector('.primary-metrics')" in script
    assert "Section targeting" in script and "Correct final outcome" in script

def test_partial_and_complete_official_run_labels(tmp_path):
    db=Database(str(tmp_path/"labels.db")); service=BenchmarkService(db,FakeSuperDocsClient()); service.import_corpus(MANIFEST)
    benchmark_run_id=service.current_benchmark_run()["id"]
    first_case=db.one("SELECT id FROM cases WHERE external_case_id IS NOT NULL ORDER BY id LIMIT 1")["id"]
    db.execute("INSERT INTO runs(case_id,benchmark_run_id,status,created_at) VALUES (?,?,?,?)",(first_case,benchmark_run_id,"completed","now"))
    assert service.metrics()["official_run_complete"] is False
    remaining=db.all("SELECT id FROM cases WHERE external_case_id IS NOT NULL AND id<>?",(first_case,))
    for case in remaining:
        db.execute("INSERT INTO runs(case_id,benchmark_run_id,status,created_at) VALUES (?,?,?,?)",(case["id"],benchmark_run_id,"completed","now"))
    assert service.metrics()["official_cases_run"]==60 and service.metrics()["official_run_complete"] is True
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "Experimental validation run — not the frozen official benchmark." in script
    assert "if(!m.official_run_complete)" in script

def test_applied_verification_summary_uses_only_applied_records(setup):
    db,fake,service,did=setup
    category=db.one("SELECT id FROM failure_categories WHERE name='other'")["id"]
    first=service.run_case(new_case(service,did,"edit",external_case_id="APPLIED-1")); service.adjudicate(first["id"],"fail",category,"original")
    service.approve_test_edit(first["id"]); service.save_applied_verification(first["id"],False,True,"landed")
    db.execute("UPDATE applied_verifications SET unrelated_changes_detected=1 WHERE run_id=?",(first["id"],))
    second=service.run_case(new_case(service,did,"edit",external_case_id="APPLIED-2")); service.adjudicate(second["id"],"pass",None,None)
    service.approve_test_edit(second["id"]); service.save_applied_verification(second["id"],True,False,"missed")
    third=service.run_case(new_case(service,did,"edit",external_case_id="NO-APPLIED")); service.adjudicate(third["id"],"pass",None,None)
    before=(service.metrics()["pass"],service.metrics()["fail"])
    summary=service.metrics()["applied_verification"]
    assert summary=={"verified":2,"landed_in_intended_section":1,"did_not_land_correctly":1,"cannot_determine":0,"unrelated_changes_detected":1}
    assert (service.metrics()["pass"],service.metrics()["fail"])==before==(2,1)

def test_empty_applied_verification_summary_and_ui_message(setup):
    _,_,service,_=setup
    assert service.metrics()["applied_verification"]=={"verified":0,"landed_in_intended_section":0,"did_not_land_correctly":0,"cannot_determine":0,"unrelated_changes_detected":0}
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "Applied edit verification" in script and "Landed correctly" in script

@pytest.mark.parametrize("case_id",["D02-C01","D02-C02"])
def test_correct_section_wrong_result_is_targeting_pass_strict_fail(case_id):
    result=assess_targeting({"case_id":case_id,"strict_verdict":"fail"})
    assert result["targeting_verdict"]=="pass"
    assert result["simplified_failure_category"]=="Right target, wrong result"

def test_wrong_section_is_targeting_fail():
    result=assess_targeting({"case_id":"D01-C02","strict_verdict":"fail"})
    assert result["targeting_verdict"]=="fail" and result["simplified_failure_category"]=="Wrong target"

def test_should_clarify_and_no_target_semantics_remain_targeting_failures():
    clarify=assess_targeting({"case_id":"D01-C03","strict_verdict":"fail"})
    unsupported=assess_targeting({"case_id":"D10-C03","strict_verdict":"fail"})
    assert clarify=={"targeting_verdict":"fail","targeting_reason":REVIEWED_STRICT_FAILURES["D01-C03"][1],"simplified_failure_category":"Should have clarified"}
    assert unsupported["targeting_verdict"]=="fail" and unsupported["simplified_failure_category"]=="Unsupported target"

def test_frozen_targeting_reclassification_is_reproducible():
    rows=[{"case_id":f"STRICT-PASS-{i}","strict_verdict":"pass"} for i in range(25)]
    rows += [{"case_id":case_id,"strict_verdict":"fail"} for case_id in REVIEWED_STRICT_FAILURES]
    assessed=[{**row,**assess_targeting(row)} for row in rows]
    assert verdict_summary(assessed,"targeting_verdict")=={"total":40,"pass":30,"fail":9,"cannot_determine":1,"accuracy":.75}
    counts={category:sum(r.get("simplified_failure_category")==category for r in assessed) for category in PUBLIC_FAILURE_DEFINITIONS}
    assert counts=={"Wrong target":5,"Should have clarified":2,"Unsupported target":2,"Right target, wrong result":5}

def test_unreviewed_attempts_remain_unscored_even_for_frozen_case_ids(setup):
    _,_,service,did=setup
    service.run_case(new_case(service,did,external_case_id="D02-C01"))
    service.run_case(new_case(service,did,external_case_id="D01-C02"))
    metrics=service.metrics()
    assert metrics["evaluated"]==0
    assert metrics["strict"]=={"total":0,"pass":0,"fail":0,"cannot_determine":0,"accuracy":0}
    assert metrics["targeting"]=={"total":0,"pass":0,"fail":0,"cannot_determine":0,"accuracy":0}
    assert metrics["by_failure_category"]==[]

def test_secondary_experiments_do_not_change_targeting_or_strict_metrics(setup):
    _,_,service,did=setup; run=service.run_case(new_case(service,did,"edit",external_case_id="SECONDARY-1")); service.adjudicate(run["id"],"pass",None,None)
    before=service.metrics(); service.approve_test_edit(run["id"]); service.save_applied_verification(run["id"],True,False,"separate")
    after=service.metrics()
    assert after["targeting"]==before["targeting"] and after["strict"]==before["strict"]

def test_budget_cap_usage_and_within_budget_are_dynamic(setup):
    _,_,service,did=setup; service.run_case(new_case(service,did,external_case_id="BUDGET-1"))
    metrics=service.metrics()
    assert metrics["budget_cap_operations"]==5 and metrics["total_operations_charged"]==1 and metrics["within_budget"] is True
    service.max_batch_operations=0
    assert service.metrics()["within_budget"] is False

def test_export_docx_button_only_for_completed_applied_edit():
    script=(ROOT/"app"/"static"/"recovery.js").read_text()
    assert "approval_status==='completed'" in script and "Export DOCX" in script

def test_tracked_final_exports_reproduce_targeting_and_strict_results():
    summary=json.loads((ROOT/"outputs"/"final_run"/"summary.json").read_text())
    with (ROOT/"outputs"/"final_run"/"results.csv").open(newline="") as handle: rows=list(csv.DictReader(handle))
    assert len(rows)==60
    assert summary["benchmark_run_id"]==4 and summary["corpus_version"]=="1.1.0"
    assert summary["targeting"]=={"total":60,"pass":56,"fail":4,"cannot_determine":0,"accuracy":56/60}
    assert summary["strict"]=={"total":60,"pass":56,"fail":4,"cannot_determine":0,"accuracy":56/60}
    assert {"targeting_verdict","strict_verdict","simplified_failure_category","targeting_reason"}<=set(rows[0])
    assert sum(r["targeting_verdict"]=="pass" and r["strict_verdict"]=="fail" for r in rows)==0
    assert summary["budget"]=={"cap_operations":60,"actual_api_reported_operations":38,"within_budget":True,"dollar_spend_usd":None,"dollar_spend_note":"Dollar spend was not exposed by the stored API responses."}
