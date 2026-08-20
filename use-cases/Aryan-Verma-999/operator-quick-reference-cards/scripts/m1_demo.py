from __future__ import annotations
import argparse, hashlib, json, os, sys, time, uuid, re, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import MANUAL, verify, write_artifacts
from linecard.fallback import compose_verified_card, verify_staging_content
from linecard.staging import map_authoritative_sections, staging_html, critical_change_allowed, proposal_slot, normalize_document_identities
from linecard.superdocs_client import SuperDocsClient, document_html, normalize_proposals, reject_unsafe_proposals, sha256_bytes
from linecard.reconciliation import bounded_diff, chunk_reconciliation, html_sha256, write_run_artifact

ROOT=Path(__file__).parents[1]
def visible(s): return re.sub(r"<[^>]+>"," ",s)
def shape_id(x): return len(str(x))


def synchronized_html_from_event(event):
    """Read the provider sync HTML when SSE is available, without guessing."""
    if not event:
        return ""
    return document_html(event.get("data", event))


def focused_document_from_event(event):
    if not event:
        return None
    payload = event.get("data", event)
    return payload.get("focused_document_id") if isinstance(payload, dict) else None

def live_m1(result):
    import fitz
    client=SuperDocsClient(); client.sessions(); manual_data=MANUAL.read_bytes(); stage=staging_html()
    request="Improve only bounded presentation prose in the LineCard Content Review staging document. Preserve every required heading, exact safety/procedure/specification/restart wording, exact value, visible page citation, and all source-backed meaning. Do not add numbers, links, scripts, or sections."
    artifact=ROOT/"artifacts/m1/live-run-sanitized.json"
    state={"architecture":"staging_plus_local_composition","run_fingerprint":hashlib.sha256((result["html_sha256"]+hashlib.sha256(manual_data).hexdigest()+request).encode()).hexdigest(),"request_hash":hashlib.sha256(request.encode()).hexdigest(),"skeleton_html_sha256":result["html_sha256"],"manual":{"durable_id_sha256":None,"pre_version":None,"pre_html_sha256":None,"post_version":None,"post_html_sha256":None},"staging":{"durable_id_sha256":None,"session_id_shape":None,"base_version":None,"base_html_sha256":None,"chat_document_html_sha256":None,"final_html_sha256":None},"proposal_rounds":[],"authoritative":{"staging_version":None,"staging_html_sha256":None,"composed_html_sha256":None},"verifier":None,"structural_diff":{},"export_attempted":False,"job_states":[],"billable_chat_operations":0,"error":None}
    def persist(): write_run_artifact(state,artifact)
    persist()
    def upload(session,name,data,ctype):
        grant=client.upload_url(name,len(data),ctype); client.put_upload(grant["upload_url"],data,ctype); return client.process_upload(grant["upload_id"],session,name)
    docs=client.documents(); entries=docs if isinstance(docs,list) else docs.get("documents",[]); manual_entry=next((x for x in entries if "manual" in str(x.get("title","")).lower() or x.get("filename")==MANUAL.name),None)
    session="linecard_m1_stage_"+uuid.uuid4().hex[:10]
    manual_id=manual_entry.get("document_id") if manual_entry else upload(session,MANUAL.name,manual_data,"application/pdf").get("document_id")
    if not manual_id: raise RuntimeError("manual ID unavailable")
    before_manual=client.detail(manual_id); state["manual"].update({"durable_id_sha256":html_sha256(str(manual_id)),"pre_version":before_manual.get("version"),"pre_html_sha256":html_sha256(document_html(before_manual))}); persist()
    client.init_session(session); processed=upload(session,"linecard-m1-staging.html",stage.encode(),"text/html"); roster=client.session_documents(session); roster=roster if isinstance(roster,list) else roster.get("documents",[]); entry=next((x for x in roster if x.get("durable_document_id") and x.get("durable_document_id")!=manual_id),{})
    stage_id=entry.get("document_id") or processed.get("document_id"); stage_durable=entry.get("durable_document_id") or processed.get("durable_document_id") or stage_id
    roster_forms=normalize_document_identities(roster)
    stage_forms=next((forms for key, forms in roster_forms.items() if stage_id in forms or stage_durable in forms), {stage_id, stage_durable})
    state["staging"]["durable_id_sha256"]=html_sha256(str(stage_durable)); state["staging"]["session_id_shape"]=shape_id(stage_id); base_detail=client.detail(stage_durable); base_html=document_html(base_detail); state["staging"].update({"base_version":base_detail.get("version"),"base_html_sha256":html_sha256(base_html)}); persist()
    stage_report=verify_staging_content(base_html)
    mapping=map_authoritative_sections(base_html, document_id=stage_durable, version=base_detail.get("version"))
    for item in mapping.values(): item["document_id_forms"] = set(stage_forms)
    if stage_report["status"]!="PASS": state["verifier"]={"stage":"staging_base","report":stage_report}; state["error"]="staging base failed before chat"; persist(); raise RuntimeError(state["error"])
    # The chat document must be byte-for-byte the provider's persisted staging
    # representation. Sending the pre-upload source here can create a second
    # chunk namespace, making proposal targets impossible to reconcile.
    state["staging"]["chat_document_html_sha256"]=html_sha256(base_html); persist()
    client.open_documents(session,[manual_id]); job=client.chat_async(session,stage_id,document_html=base_html,message=request); state["billable_chat_operations"]=client.budget.used; job_id=job["job_id"]; prospective=base_html; deadline=time.time()+180; rounds=0; approved=0; rejected=0
    stream_events=[]
    def collect_stream():
        try:
            stream_events.extend(client.stream_events(session, job_id, last_sequence=0))
        except Exception as exc:
            state["stream_error"] = type(exc).__name__
    stream_thread=threading.Thread(target=collect_stream, daemon=True); stream_thread.start()
    while time.time()<deadline:
        current=client.job(job_id); status=current.get("status"); state["job_states"].append(status); persist()
        if status in {"completed","failed","cancelled"}: break
        if status=="awaiting_approval":
            recovery=client.pending_review(session); state["pending_review_recovery"]={"job_id_hash":hashlib.sha256(job_id.encode()).hexdigest(),"status":recovery.get("job",{}).get("status") if recovery.get("job") else status,"pending_change_count":len(recovery.get("pending_changes",[])),"pending_batch_decisions_shape":type(recovery.get("pending_batch_decisions")).__name__}; persist()
            deadline_sync=time.time()+10
            while not any(e.get("type")=="document_sync" for e in stream_events) and time.time()<deadline_sync: time.sleep(.25)
            sync_event=next((e for e in stream_events if e.get("type")=="document_sync"),None)
            sync_html=synchronized_html_from_event(sync_event)
            sync_source="sse_document_sync"
            focused_document=focused_document_from_event(sync_event)
            if focused_document and focused_document not in stage_forms:
                state["error"]="document_sync belongs to a different focused document; no decision submitted"; persist(); raise RuntimeError(state["error"])
            if not sync_html:
                # Pending proposals do not mutate the staging document. The
                # durable read-back is therefore the same authoritative base
                # needed for ownership reconciliation when SSE is unavailable.
                sync_html=document_html(client.detail(stage_durable))
                sync_source="durable_document_readback"
            if not sync_html: state["error"]="document_sync not captured before proposal review"; persist(); raise RuntimeError(state["error"])
            mapping=map_authoritative_sections(sync_html, document_id=stage_durable, version=base_detail.get("version"))
            for item in mapping.values(): item["document_id_forms"] = set(stage_forms)
            state["document_sync"]={"sequence":sync_event.get("sequence") if sync_event else None,"type":"document_sync" if sync_event else "durable_document_readback","source":sync_source,"focused_document_id_sha256":html_sha256(str(focused_document)) if focused_document else None,"document_id_forms_sha256":hashlib.sha256("|".join(sorted(stage_forms)).encode()).hexdigest(),"html_sha256":html_sha256(sync_html),"slots":{k:{"provider_chunk_count":len(v.get("provider_chunk_ids",[])),"provider_chunk_id_hashes":sorted(html_sha256(str(chunk)) for chunk in v.get("provider_chunk_ids",[])),"base_text_hash":v["old_text_fingerprint"]} for k,v in mapping.items()}}; persist()
            rounds+=1; proposals=normalize_proposals((current.get("metadata") or {}).get("pending_changes",[])); reject_unsafe_proposals(proposals,stage_id,manual_id); rr={"round":rounds,"base_html_sha256":html_sha256(prospective),"proposals":[],"decisions":[],"prospective_staging_html_sha256":None}; decisions=[]
            reconciliation=chunk_reconciliation(mapping,proposals)
            resolved_slots={}; unresolved=[]
            for p in proposals:
                cid=p.get("change_id") or p.get("id")
                try: resolved_slots[cid]=proposal_slot(p,mapping)
                except ValueError as exc: unresolved.append({"change_id":cid,"reason":str(exc)})
            state["provider_reconciliation"]={**reconciliation,"round":rounds,"unresolved_change_count":len(unresolved),"unresolved_reasons":sorted({item["reason"] for item in unresolved})}
            if unresolved:
                state["error"]="provider proposals have no direct, authoritative synchronized chunk owner; no decision submitted"
                persist()
                raise RuntimeError(state["error"])
            for p in proposals:
                cid=p.get("change_id") or p.get("id"); old=p.get("old_html") or ""; new=p.get("new_html") or p.get("after") or old; slot=None
                slot=resolved_slots[cid]
                before_text=visible(old); after_text=visible(new); eligible,reason=critical_change_allowed(slot,before_text,after_text)
                if eligible and old and old in prospective:
                    candidate=prospective.replace(old,new,1)
                else: candidate=prospective
                eligible=eligible and verify_staging_content(candidate)["status"]=="PASS"
                if eligible: prospective=candidate
                rr["proposals"].append({"change_id_sha256":html_sha256(str(cid)),"document_id_sha256":html_sha256(str(p.get("document_id") or p.get("target_document_id") or "")),"slot_id":slot,"old_html_sha256":html_sha256(old),"new_html_sha256":html_sha256(new),"eligibility":eligible,"reason":reason if not eligible else "eligible"})
                decision={"change_id":cid,"approved":eligible,"feedback":None if eligible else reason}; decisions.append(decision); rr["decisions"].append(decision); approved+=int(eligible); rejected+=int(not eligible)
            rr["prospective_staging_html_sha256"]=html_sha256(prospective); state["proposal_rounds"].append(rr); persist(); client.approve(session,job_id,decisions)
        time.sleep(2)
    if current.get("status")!="completed": state["error"]=f"staging job ended {current.get('status')}"; persist(); raise RuntimeError(state["error"])
    stream_thread.join(timeout=5); state["stream"]={"events":[{"sequence":e.get("sequence"),"type":e.get("type")} for e in stream_events],"monotonic":all(a.get("sequence",0)<b.get("sequence",0) for a,b in zip(stream_events,stream_events[1:]))}; persist()
    final_stage_detail=client.detail(stage_durable); final_stage=document_html(final_stage_detail); final_mapping=map_authoritative_sections(final_stage, document_id=stage_durable, version=final_stage_detail.get("version")); state["staging"]["final_html_sha256"]=html_sha256(final_stage); state["authoritative"].update({"staging_version":final_stage_detail.get("version"),"staging_html_sha256":html_sha256(final_stage)}); composed,composition=compose_verified_card(final_stage); final_report=verify(composed); state["authoritative"]["composed_html_sha256"]=html_sha256(composed); state["verifier"]={"staging":verify_staging_content(final_stage),"composition":composition,"final":final_report}; state["structural_diff"]=bounded_diff(result["html"],composed); persist()
    if final_report["status"]!="PASS": state["error"]="composed final card failed verifier"; persist(); raise RuntimeError(state["error"])
    state["export_attempted"]=True; persist(); exported=client.export_pdf_html(composed); pdf=exported.content; out=ROOT/"artifacts/m1"; out.mkdir(parents=True,exist_ok=True); (out/"linecard-m1.pdf").write_bytes(pdf); pdfdoc=fitz.open(stream=pdf,filetype="pdf"); text="\n".join(p.get_text() for p in pdfdoc); pf={"pages":len(pdfdoc),"exact_value":"24 N·m ± 2 N·m" in text,"safety":"Isolate electrical and pneumatic energy before clearing a jam.","procedures":all(x in text for x in ("Stop the infeed.","Verify stored energy is released.","Remove the obstruction using the approved tool.")),"restart":"Replace the guard and verify the interlock before restart" in text,"citation":"PDF p. 3" in text}; after_manual=client.detail(manual_id); state["manual"].update({"post_version":after_manual.get("version"),"post_html_sha256":html_sha256(document_html(after_manual))}); persist()
    return {"architecture":"staging_plus_local_composition","live_chat_operations":client.budget.used,"proposal_rounds":rounds,"approved":approved,"rejected":rejected,"staging_html_sha256":html_sha256(final_stage),"composed_html_sha256":html_sha256(composed),"verifier":final_report,"manual_unchanged":state["manual"]["pre_version"]==state["manual"]["post_version"] and state["manual"]["pre_html_sha256"]==state["manual"]["post_html_sha256"],"export_status":exported.status_code,"pdf_sha256":sha256_bytes(pdf),"pdf_bytes":len(pdf),"pdf_pages":len(pdfdoc),"pdf_postflight":pf}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); args=ap.parse_args(); result=write_artifacts(); report=verify(result["html"]); out={"mode":"dry-run" if args.dry_run else "offline","manual_sha256":result["mapping"]["manual_sha256"],"page_count":4,"evidence_records":6,"skeleton_html_sha256":result["html_sha256"],"verifier":report,"live":False}
    if not args.dry_run and os.getenv("RUN_LIVE_SUPERDOCS")=="1":
        try: out["live_result"]=live_m1(result); out["live"]=True
        except Exception as exc: out["live"]=True; out["live_error"]=type(exc).__name__+": "+str(exc); print(json.dumps(out,indent=2,ensure_ascii=False)); return 2
    print(json.dumps(out,indent=2,ensure_ascii=False)); return 0 if report["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
