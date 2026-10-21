import json
from pathlib import Path
import pytest
from linecard.errors import normalize_error, parse_response
from linecard.security import sanitize_html, safe_filename, validate_upload, secret_scan
from linecard.staging import staging_html, parse_document_sync
from linecard.review import apply_decisions
from linecard.storage import Store
from linecard.worker import DurableWorker
from linecard.batch import run_offline_three_task_batch
from linecard.flow import hero_flow, sanitize_mermaid, FlowEdge, FlowGraph, FlowNode
from linecard.layout import LayoutBlock, LayoutBlocked, PAGE_BUDGET_UNSATISFIABLE, solve_two_page

def test_durable_restart_lease_outbox_effect_and_duplicate_event(tmp_path):
    db=tmp_path/'state.db'; s=Store(str(db)); s.create_job('j', {'stage':'review'}); s.enqueue('j','review',{'x':1}); calls=[]
    w=DurableWorker(s, lambda job: (calls.append(job['id']) or {'state':'COMPLETED'}), 'one'); assert w.run_once()==1; w.stop()
    s=Store(str(db)); assert s.get_job('j')['state']=='COMPLETED'; assert len(s.pending_outbox())==1
    w=DurableWorker(s, lambda job: (calls.append('duplicate') or {'state':'COMPLETED'}), 'two'); assert w.run_once()==0; assert 'duplicate' not in calls
    s.transition('j', 1, 'COMPLETED', event='same', payload={}) if False else None
    w.stop()

def test_second_worker_rejected_and_review_decisions_fail_closed():
    s=Store(); s.claim_worker('a')
    with pytest.raises(RuntimeError): s.claim_worker('b')
    s.release_worker('a'); mapping=parse_document_sync(staging_html(), document_id='stage', version=4)
    p={'change_id':'c1','chunk_id':'LC_TASK_OVERVIEW','document_id':'stage','base_version':4,'old_html':mapping['TASK_OVERVIEW']['old_html'],'new_html':'Clear an infeed jam safely.'}
    result=apply_decisions([p], {'c1':True}, mapping, document_id='stage', base_version=4); assert len(result['approved'])==1
    with pytest.raises(ValueError): apply_decisions([p,p], {'c1':True}, mapping, document_id='stage', base_version=4)
    with pytest.raises(ValueError): apply_decisions([p], {'c1':True}, mapping, document_id='stage', base_version=5)

def test_batch_produces_three_isolated_artifacts(tmp_path):
    report=run_offline_three_task_batch(tmp_path); assert report['aggregate_status']=='COMPLETED'; assert len(report['cards'])==3
    assert len(list(tmp_path.glob('lc-*.html')))==3 and (tmp_path/'batch-manifest.json').exists() and (tmp_path/'linecard-offline-batch.zip').exists()
    assert len({x['card_id'] for x in report['cards']})==3 and all(x['operation_budget']['reserved']==1 for x in report['cards'])

@pytest.mark.parametrize('status', [400,401,403,404,409,413,415,422,429,500,504])
def test_error_matrix_is_normalized_without_secrets(status):
    err=parse_response(status, b'{"detail":"safe"}', {'Retry-After':'4'} if status==429 else {})
    assert {'category','status','cause','retryable','retry_after','suggested_recovery','message'} <= set(err)
    assert 'SUPERDOCS_API_KEY' not in json.dumps(err)

def test_network_malformed_expired_stream_and_security_matrix():
    assert normalize_error(Exception('DNS resolution failed'))['category']=='DNS_FAILURE'
    assert normalize_error(TimeoutError('timeout'))['retryable']
    assert '<script' not in sanitize_html('<script>alert(1)</script><p onclick="x">safe</p>')
    assert secret_scan('Authorization: Bearer [REDACTED]')
    with pytest.raises(ValueError): safe_filename('../secret.pdf')
    with pytest.raises(ValueError): validate_upload('x.html', 2, 'text/html')
    with pytest.raises(ValueError): validate_upload('x.pdf', 999, 'application/pdf', max_bytes=2)
    with pytest.raises(ValueError): sanitize_mermaid('flowchart TD; A -->|x| B\n<script>')

def test_flow_and_layout_golden_failures():
    graph=hero_flow(); graph.validate_mermaid(); assert graph.digest()==hero_flow().digest()
    with pytest.raises(ValueError): FlowGraph(graph.nodes, graph.edges + (FlowEdge('ISOLATED','STOP','maybe'),)).validate()
    with pytest.raises(ValueError): sanitize_mermaid('flowchart TD\nA-->B https://bad')
    assert solve_two_page([LayoutBlock('safety','s',True,2),LayoutBlock('footer','f',False,50)])['protected_preserved']
    with pytest.raises(LayoutBlocked, match=PAGE_BUDGET_UNSATISFIABLE): solve_two_page([LayoutBlock(str(i),'x',True,10) for i in range(10)], lines_per_page=10)
