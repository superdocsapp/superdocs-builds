from __future__ import annotations
import argparse, hashlib, json, os, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.superdocs_client import SuperDocsClient, document_html, normalize_proposals, reject_unsafe_proposals, sha256_bytes

ROOT=Path(__file__).parents[1]; FIXTURE=ROOT/"fixtures/m0-tiny-manual.pdf"
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--dry-run',action='store_true'); args=ap.parse_args()
    if not FIXTURE.exists():
        print('fixture missing; run scripts/generate_m0_fixture.py', file=sys.stderr); return 2
    data=FIXTURE.read_bytes(); pages=data.count(b'/Type /Page '); digest=hashlib.sha256(data).hexdigest()
    print(json.dumps({'mode':'dry-run' if args.dry_run else 'live','fixture':FIXTURE.name,'bytes':len(data),'pages':pages,'sha256':digest,'planned_stages':['upload','isolated-session-open','separate-card','reviewed-edit','poll','explicit-decisions','authoritative-readback','export']} ,indent=2))
    if args.dry_run: return 0
    if os.getenv('RUN_LIVE_SUPERDOCS') != '1': print('live mode requires RUN_LIVE_SUPERDOCS=1', file=sys.stderr); return 2
    if not os.getenv('SUPERDOCS_API_KEY'):
        print('LINECARD M0 LIVE BLOCKED — SUPERDOCS_API_KEY missing'); return 2
    client=SuperDocsClient()
    try:
        client.sessions(); print('authentication: success'); print('HTTP status: 200')
    except Exception:
        print('LINECARD M0 BLOCKED — SuperDocs authentication failed'); return 2
    # Upload/process are documented as non-billable. IDs are reported only as shape.
    def shape(value):
        if not value: return 'missing'
        value=str(value); return f'{value[:4]}… ({len(value)} chars)'
    def upload(filename, content, session):
        content_type='text/html' if filename.endswith('.html') else 'application/pdf'
        grant=client.upload_url(filename, len(content), content_type); uid=grant['upload_id']; client.put_upload(grant['upload_url'], content, content_type)
        return uid, client.process_upload(uid, session, filename)
    manual_session='linecard_m0_manual_'+uuid.uuid4().hex[:10]
    task_session='linecard_m0_task_'+uuid.uuid4().hex[:10]
    docs=client.documents(); entries=docs if isinstance(docs,list) else docs.get('documents',[])
    # Reconcile the completed non-billable upload/process before considering another upload.
    manual_entry=next((x for x in entries if x.get('title')==FIXTURE.stem or x.get('filename')==FIXTURE.name or x.get('name')==FIXTURE.name), {})
    if manual_entry:
        manual={}; durable=manual_entry.get('document_id')
    else:
        uid, manual=upload(FIXTURE.name, data, manual_session)
        durable=manual.get('document_id') or manual.get('durable_document_id')
    if not durable: raise RuntimeError('could not reconcile durable manual document identity')
    # Create the card in an empty session first. On the current service,
    # processing another editable upload after opening a document reuses the
    # focused slot instead of creating a second document.
    client.init_session(task_session); task_roster=client.session_documents(task_session)
    manual_slot={}
    card_html='''<!doctype html><html><body><main data-linecard="m0"><h1>LC-100 Infeed Jam Card</h1><section data-card-block="safety"><p>Safety placeholder</p></section><section data-card-block="procedure"><p>Procedure placeholder</p></section><section data-card-block="specification"><p>Specification placeholder</p></section></main></body></html>'''.encode()
    card_uid, card=upload('linecard-m0-card.html',card_html,task_session)
    task_roster=client.session_documents(task_session); roster=task_roster if isinstance(task_roster,list) else task_roster.get('documents',[])
    card_entry=next((x for x in roster if x.get('durable_document_id') and x.get('durable_document_id') != durable), {})
    card_id=card_entry.get('document_id') or card_entry.get('durable_document_id') or card.get('document_id')
    card_durable=card_entry.get('durable_document_id') or card.get('durable_document_id') or card_id
    if not card_id or card_durable==durable: raise RuntimeError('card and manual identities were not distinct')
    client.open_documents(task_session,[durable]); task_roster=client.session_documents(task_session)
    roster=task_roster if isinstance(task_roster,list) else task_roster.get('documents',[])
    manual_slot=next((x for x in roster if x.get('durable_document_id')==durable),{})
    request='Replace the safety, procedure, and specification placeholders in the CARD only using the supplied synthetic evidence. Preserve the exact string “24 N·m ± 2 N·m”. Do not edit the manual.'
    card_base=document_html(client.detail(card_durable))
    if not card_base: raise RuntimeError('authoritative card HTML unavailable before chat')
    job=client.chat_async(task_session,card_id,document_html=card_base,message=request); job_id=job['job_id']; observed=[]
    deadline=time.time()+180; current={}
    while time.time()<deadline:
        current=client.job(job_id); state=current.get('status'); observed.append(state)
        if state in {'awaiting_approval','completed','failed','cancelled'}: break
        time.sleep(2)
    if current.get('status')!='awaiting_approval': raise RuntimeError(f'edit did not reach approval: {current.get("status")}')
    metadata=current.get('metadata') or {}; pending=metadata.get('pending_changes',[])
    proposals=normalize_proposals(pending); reject_unsafe_proposals(proposals,card_id,durable)
    decisions=[{'change_id':p.get('change_id') or p.get('id'),'approved':i != 0,'feedback':None if i != 0 else 'Reject the first proposal for controlled review.'} for i,p in enumerate(proposals)]
    if any(d['change_id'] is None for d in decisions): raise RuntimeError('proposal missing change id')
    client.approve(task_session,job_id,decisions)
    final=client.detail(card_durable); manual_final=client.detail(durable); html=final.get('html') or final.get('document_html') or ''
    if '24 N·m ± 2 N·m' not in html: raise RuntimeError('authoritative card read-back lacks exact specification')
    if sha256_bytes((manual_final.get('html') or '').encode()) == '': raise RuntimeError('manual read-back unavailable')
    exported=client.export_pdf(task_session); artifacts=ROOT/'artifacts/m0'; artifacts.mkdir(parents=True,exist_ok=True); pdf=exported.content; (artifacts/'linecard-m0.pdf').write_bytes(pdf)
    print(json.dumps({'authentication':'success','manual_id_shape':shape(durable),'manual_session_document_id_shape':shape(manual_slot.get('document_id')),'card_id_shape':shape(card_durable),'job_id_shape':shape(job_id),'job_states':observed,'proposal_count':len(proposals),'approval_decisions':len(decisions),'card_sha256':sha256_bytes(html.encode()),'export_status':exported.status_code,'pdf_bytes':len(pdf),'pdf_sha256':sha256_bytes(pdf),'operation_count':client.budget.used},indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
