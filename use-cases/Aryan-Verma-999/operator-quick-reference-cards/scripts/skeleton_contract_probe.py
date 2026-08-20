"""Non-billable card-base fidelity probe. This script never calls chat."""
from __future__ import annotations
import argparse, hashlib, json, os, sys, uuid
import re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import verify, write_artifacts
from linecard.reconciliation import html_sha256
from linecard.superdocs_client import SuperDocsClient, document_html, response_items

ROOT=Path(__file__).parents[1]

def structure_summary(text):
    visible=re.sub(r"<style.*?</style>|<script.*?</script>"," ",text,flags=re.S|re.I); visible=re.sub(r"<[^>]+>"," ",visible)
    return {"doctype":text.lower().startswith("<!doctype html>"),"body":bool(re.search(r"<body\b",text,re.I)),"page_classes":re.findall(r'class="([^"]*card-page[^"]*)"',text),"page_break": "page-break-after:always" in text,"protected_count":text.count("data-protected"),"evidence_ids":sorted(set(re.findall(r'data-evidence-ids="([^"]+)"',text))),"spec_ids":sorted(set(re.findall(r'data-spec-id="([^"]+)"',text))),"safety_ids":sorted(set(re.findall(r'data-safety-id="([^"]+)"',text))),"step_ids":sorted(set(re.findall(r'data-step-id="([^"]+)"',text))),"visible_markers":{k:(v in visible) for k,v in {"page_3":"PDF p. 3","exact_value":"24 N·m ± 2 N·m","safety":"Isolate electrical and pneumatic energy before clearing a jam.","procedure":"Stop the infeed.","restart":"Replace the guard and verify the interlock before restart."}.items()}}
def structural_compare(local, authoritative):
    a=structure_summary(local); b=structure_summary(authoritative)
    return {"local":a,"authoritative":b,"retained":{k:(a[k]==b[k]) for k in a},"normalized_or_stripped":[k for k in a if a[k]!=b[k]]}

def postflight(pdf):
    import fitz
    doc=fitz.open(stream=pdf,filetype="pdf"); text="\n".join(p.get_text() for p in doc)
    return {"opens":True,"pages":len(doc),"exact_value":"24 N·m ± 2 N·m" in text,"safety":"Isolate electrical and pneumatic energy before clearing a jam." in text,"procedure":all(x in text for x in ("Stop the infeed.","Verify stored energy is released.","Remove the obstruction using the approved tool.")),"restart":"Replace the guard and verify the interlock before restart." in text,"citation":"PDF p. 3" in text}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); args=ap.parse_args(); local=write_artifacts(); html=local["html"]
    if args.dry_run:
        print(json.dumps({"mode":"dry-run","chat_calls":0,"paths":["A_html_upload","B_blank_save"],"skeleton_sha256":html_sha256(html),"base_gate":"not run offline"},indent=2)); return 0
    if os.getenv("RUN_LIVE_SUPERDOCS") != "1": print("live probe requires RUN_LIVE_SUPERDOCS=1",file=sys.stderr); return 2
    client=SuperDocsClient(); client.sessions(); results=[]
    def fresh(): return "linecard_m1_probe_"+uuid.uuid4().hex[:10]
    def finish(path,session,doc_id,detail):
        authoritative=document_html(detail); report=verify(authoritative); item={"path":path,"session_document_id_shape":len(str(doc_id)),"authoritative_html_sha256":html_sha256(authoritative),"local_skeleton_sha256":html_sha256(html),"structural_comparison":structural_compare(html,authoritative),"base_verifier":report,"export_attempted":False}
        if report["status"]=="PASS":
            exported=client.export_pdf(session); pf=postflight(exported.content); item.update({"export_attempted":True,"export_status":exported.status_code,"pdf_sha256":hashlib.sha256(exported.content).hexdigest(),"pdf_bytes":len(exported.content),"pdf_postflight":pf})
        results.append(item)
    # A: exact current upload/process path.
    session=fresh(); client.init_session(session); grant=client.upload_url("linecard-m1-probe.html",len(html.encode()),"text/html"); client.put_upload(grant["upload_url"],html.encode(),"text/html"); processed=client.process_upload(grant["upload_id"],session,"linecard-m1-probe.html"); roster=response_items(client.session_documents(session),"documents"); entry=next((x for x in roster if x.get("durable_document_id")),{}); did=entry.get("durable_document_id") or processed.get("durable_document_id") or processed.get("document_id"); finish("A_html_upload",session,did,client.detail(did))
    # B: documented blank document followed by human-style save.
    session=fresh(); client.init_session(session); blank=client.blank_document(session); roster=response_items(client.session_documents(session),"documents"); entry=next((x for x in roster if x.get("document_id") or x.get("durable_document_id")),{}); local_id=entry.get("document_id") or blank.get("document_id"); saved=client.save_document(session,local_id,html); roster=response_items(client.session_documents(session),"documents"); entry=next((x for x in roster if x.get("document_id") == local_id or x.get("durable_document_id")),{}); durable=entry.get("durable_document_id") or saved.get("durable_document_id") or saved.get("version_id") or blank.get("durable_document_id");
    if not durable or durable == local_id: raise RuntimeError("blank/save did not expose a durable document ID")
    finish("B_blank_save",session,durable,client.detail(durable))
    from linecard.reconciliation import write_run_artifact
    report={"chat_calls":0,"paths":results}; write_run_artifact(report,ROOT/"artifacts/m1/skeleton-probe.json"); print(json.dumps(report,indent=2,ensure_ascii=False)); return 0 if all(x["base_verifier"]["status"]=="PASS" for x in results) else 1
if __name__=="__main__": raise SystemExit(main())
