import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './styles.css';

type Evidence = {id: string; page: string; printed_page: string; kind: string; quote: string; bbox: number[]; reason: string; included: boolean};
type Verification = {status: 'PASS' | 'BLOCKED'; checks: Array<{check_id: string; passed: boolean; reason: string}>};
type CardClaim = {evidence_id: string; text: string; page: string; included: boolean; kind: string};
type Card = {machine: string; task: string; complete: boolean; missing_evidence_ids: string[]; safety: CardClaim; tools: CardClaim; procedure: CardClaim[]; specification: CardClaim; restart: CardClaim; stop: string; source_index: CardClaim[]; disclaimer: string};
type Demo = {task: string; status: string; evidence: Evidence[]; included_count: number; required_count: number; manual_url: string; live_limitations: string; verification: Verification | null; card: Card};
type ScaleCheck = {fixture: string; page_count: number; byte_size: number; sha256: string; ingest_ms: number; index_ms: number; retrieval_ms: number; retrieval_hits: number; matched_pages: number[]; manual_url: string; card_eligibility: string};
type ExportReceipt = {download_url: string; pdf_sha256: string; page_count: number; included_evidence_ids: string[]};

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : undefined);
  if (!response.ok) throw new Error((await response.json().catch(() => ({detail: 'Request failed'}))).detail || 'Request failed');
  return response.json() as Promise<T>;
}

function App() {
  const [demo, setDemo] = useState<Demo | null>(null);
  const [task, setTask] = useState('Clear a jam on the infeed');
  const [selected, setSelected] = useState<Evidence | null>(null);
  const [message, setMessage] = useState('Loading source evidence…');
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [scale, setScale] = useState<ScaleCheck | null>(null);
  const [receipt, setReceipt] = useState<ExportReceipt | null>(null);

  const refresh = async (operation: () => Promise<Demo>) => {
    try {
      const next = await operation();
      setDemo(next);
      setTask(next.task);
      setSelected(current => next.evidence.find(item => item.id === current?.id) || next.evidence[0] || null);
      setDownloadUrl(null);
      setReceipt(null);
      setMessage(next.verification?.status === 'BLOCKED' ? 'Export blocked — restore the required source evidence.' : next.status.replace('_', ' '));
    } catch (error) {
      setMessage(`Request failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  };

  useEffect(() => { void refresh(() => request<Demo>('/api/demo')); }, []);

  if (!demo || !selected) return <main className="loading"><p role="status">{message}</p></main>;
  const blocked = demo.verification?.status === 'BLOCKED';
  const verified = demo.verification?.status === 'PASS';
  const exportCard = async () => {
    try {
      const result = await request<ExportReceipt>('/api/demo/export', {});
      setDownloadUrl(result.download_url);
      setReceipt(result);
      setMessage('Verified two-page PDF ready');
    } catch (error) {
      setMessage(`Export blocked: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  };
  const runSafetyGap = () => {
    const safety = demo.evidence.find(item => item.id === 'SAFE-001');
    if (safety) void refresh(() => request<Demo>('/api/demo/evidence/SAFE-001', {included: !safety.included}));
  };
  const runScaleCheck = async () => {
    try {
      const result = await request<ScaleCheck>('/api/demo/scale', {});
      setScale(result);
      setMessage(`400-page scale check complete — ${result.retrieval_hits} retrieval hits`);
    } catch (error) {
      setMessage(`Scale check failed: ${error instanceof Error ? error.message : 'unknown error'}`);
    }
  };

  return <main className="linecard-app">
    <header className="app-header">
      <div className="brand"><span className="brand-mark">LC</span><strong>LineCard</strong><span>Source-locked operator cards</span></div>
      <div className="header-actions"><span className={`status ${blocked ? 'blocked' : verified ? 'verified' : ''}`} role="status">{message}</span><a className="button secondary" href={demo.manual_url} target="_blank" rel="noreferrer">Open manual ↗</a>{downloadUrl ? <a className="button primary" href={downloadUrl}>Download PDF ↓</a> : <button className="button primary" disabled={!verified} onClick={() => void exportCard()}>Export PDF ↓</button>}</div>
    </header>

    <div className="review-layout">
      <aside className="review-panel">
        <div className="panel-heading"><span>REVIEW WORKFLOW</span><h1>Build a safe card</h1><p>LineCard checks source evidence before a card can be released.</p></div>
        <div className="task-form"><label htmlFor="task">Operator task</label><div><input id="task" aria-describedby="task-help" value={task} onChange={event => setTask(event.target.value)} /><button onClick={() => void refresh(() => request<Demo>('/api/demo/retrieve', {task}))}>Retrieve</button></div><small id="task-help">This public fixture supports the infeed-jam task only.</small></div>
        <section className="scale-check" aria-labelledby="scale-title"><span>MANUAL SCALE CHECK</span><h2 id="scale-title">Test the full 400-page manual</h2><p>Runs local PDF ingest, indexing, and retrieval against the committed fixture. It does not create or unlock a card.</p><button onClick={() => void runScaleCheck()}>Run 400-page scale check</button>{scale && <div className="scale-result" role="status"><strong>{scale.page_count} pages indexed</strong><span>{scale.retrieval_hits} retrieval hits · pp. {scale.matched_pages.join(', ') || 'none'}</span><span>Ingest {scale.ingest_ms} ms · Index {scale.index_ms} ms · Search {scale.retrieval_ms} ms</span><a href={scale.manual_url} target="_blank" rel="noreferrer">Open 400-page fixture ↗</a><small>Scale proof only — a card still needs its own evidence review.</small></div>}</section>
        <section className="evidence-panel" aria-labelledby="evidence-title"><div className="evidence-heading"><div><span>SOURCE EVIDENCE</span><h2 id="evidence-title">{demo.included_count}/{demo.required_count} source spans</h2></div><small>Click a record to inspect it</small></div>{demo.evidence.map(item => <article className={`evidence-item${selected.id === item.id ? ' selected' : ''}`} key={item.id} onClick={() => setSelected(item)}><div className="evidence-meta"><span className={`evidence-state ${item.included ? 'included' : 'missing'}`} aria-label={item.included ? 'Included' : 'Excluded'} /> <strong>{item.id}</strong><span>{item.page}</span></div><p>{item.quote}</p><div className="evidence-actions"><small>{item.kind} · exact manual span</small><button aria-label={`${item.included ? 'Reject' : 'Include'} ${item.id}`} onClick={event => { event.stopPropagation(); void refresh(() => request<Demo>(`/api/demo/evidence/${item.id}`, {included: !item.included})); }}>{item.included ? 'Included' : 'Restore'}</button></div></article>)}</section>
        <section className="source-inspector" aria-label="Manual evidence viewer"><span>SELECTED SOURCE</span><strong>{selected.id} · {selected.page}</strong><figure className="source-page-preview"><img src={`/api/demo/evidence/${selected.id}/preview`} alt={`Manual page with ${selected.id} highlighted`} /><figcaption>Exact source span highlighted</figcaption></figure><p>{selected.quote}</p><a href={demo.manual_url} target="_blank" rel="noreferrer">Open the synthetic manual ↗</a></section>
        <button className="verify-card" onClick={() => void refresh(() => request<Demo>('/api/demo/verify', {}))}>Verify this card <span>→</span></button>
        <button className="scenario-button" onClick={runSafetyGap}>{demo.card.safety.included ? 'Run safety-gap scenario' : 'Restore safety scenario'} <span>↗</span></button>
        <p className="provider-boundary" role="note">{demo.live_limitations}</p>
      </aside>

      <section className="card-workspace" aria-label="Operator card preview">
        <div className="workspace-header"><div><span>GENERATED CARD PREVIEW</span><h2>{demo.card.task}</h2><p>{demo.card.machine} · changes as evidence is included or excluded</p></div><div className={`review-chip ${blocked || !demo.card.complete ? 'blocked' : verified ? 'verified' : ''}`}>{!demo.card.complete ? `${demo.card.missing_evidence_ids.length} source gap${demo.card.missing_evidence_ids.length === 1 ? '' : 's'}` : verified ? 'Source lock verified' : 'Ready for review'}</div></div>
        <div className="review-timeline" aria-label="Review progress"><div className="done"><b>01</b><span>Manual evidence</span><small>{demo.included_count}/{demo.required_count} selected</small></div><i>→</i><div className={demo.card.complete ? 'done' : 'blocked'}><b>02</b><span>Card regenerated</span><small>{demo.card.complete ? 'All sections sourced' : 'Protected gaps shown'}</small></div><i>→</i><div className={verified ? 'done' : blocked ? 'blocked' : ''}><b>03</b><span>Source lock</span><small>{verified ? 'Verified' : blocked ? 'Blocked' : 'Awaiting review'}</small></div><i>→</i><div className={receipt ? 'done' : ''}><b>04</b><span>Release PDF</span><small>{receipt ? 'Prepared' : 'Gated'}</small></div></div>
        <div className="pages">
          <article className="card-page" aria-label="Operator card page 1"><div className="page-eyebrow">LINECARD / {demo.card.machine.toUpperCase()}</div><h1>{demo.card.task}</h1><div className="page-subline"><span>Operator quick-reference card</span><span>Evidence-driven draft</span></div><section className={`safety-gate${demo.card.safety.included ? '' : ' missing'}${selected.id === demo.card.safety.evidence_id ? ' spotlight' : ''}`}><div>SAFETY GATE <span className="source-tag">{demo.card.safety.evidence_id} · {demo.card.safety.page}</span></div><strong>{demo.card.safety.text}</strong><p>{demo.card.safety.included ? 'Do not begin until stored energy is released and the area is clear.' : 'This protected section cannot be released without its source evidence.'}</p></section><div className="top-grid"><section><h2>Before you start</h2><ul className="checklist"><li className={`${demo.card.tools.included ? '' : 'missing'}${selected.id === demo.card.tools.evidence_id ? ' spotlight' : ''}`}>{demo.card.tools.text} <span className="source-tag">{demo.card.tools.evidence_id} · {demo.card.tools.page}</span></li><li>Machine stopped and isolated</li></ul></section><section className={`specification${demo.card.specification.included ? '' : ' missing'}${selected.id === demo.card.specification.evidence_id ? ' spotlight' : ''}`}><span>EXACT SPECIFICATION</span><strong>{demo.card.specification.text}</strong><b>{demo.card.specification.evidence_id} · {demo.card.specification.page}</b></section></div><section><h2>Procedure</h2><ol className="procedure">{demo.card.procedure.map((step, index) => <li className={`${step.included ? '' : 'missing'}${selected.id === step.evidence_id ? ' spotlight' : ''}`} key={step.evidence_id}><span>{String(index + 1).padStart(2, '0')}</span><div><strong>{step.text}</strong><small>{step.evidence_id} · {step.page}</small></div></li>)}</ol></section><footer><span>OEM manual and site procedures remain authoritative.</span><span>01 / 02</span></footer></article>
          <article className="card-page" aria-label="Operator card page 2"><div className="page-eyebrow">LINECARD / RETURN TO SERVICE</div><h1>Restart and<br/>verify</h1><section className="flow"><div>Energy isolated<small>Confirmed</small></div><i>→</i><div>Clear obstruction<small>Approved tool</small></div><i>→</i><div>Guard replaced<small>Torque checked</small></div><i>→</i><div>Interlock verified<small>Return to service</small></div></section><section className={`restart${demo.card.restart.included ? '' : ' missing'}${selected.id === demo.card.restart.evidence_id ? ' spotlight' : ''}`}><div><h2>Restart check</h2><p>{demo.card.restart.text}</p><span className="source-tag">{demo.card.restart.evidence_id} · {demo.card.restart.page}</span></div><b>CHECK<br/>BEFORE<br/>RESTART</b></section><section className="stop"><h2>Stop / escalate</h2><p>{demo.card.stop}</p></section><section className="source-index"><h2>Source index</h2>{demo.card.source_index.map(item => <div className={`${item.included ? '' : 'missing'}${selected.id === item.evidence_id ? ' spotlight' : ''}`} key={item.evidence_id}><strong>{item.evidence_id}</strong><span>{item.included ? item.kind : 'Evidence required'}</span><b>{item.page}</b></div>)}</section><p className="disclaimer">{demo.card.disclaimer}</p><footer><span>Source-lock status: {!demo.card.complete ? 'INCOMPLETE' : blocked ? 'BLOCKED' : verified ? 'VERIFIED' : 'READY FOR REVIEW'}</span><span>02 / 02</span></footer></article>
        </div>
        {receipt && <section className="export-receipt" aria-label="Export receipt"><div><span>RELEASE RECEIPT</span><strong>{receipt.page_count}-page reviewed PDF prepared</strong></div><p><b>SHA-256</b> {receipt.pdf_sha256.slice(0, 16)}… · {receipt.included_evidence_ids.length} source spans locked</p><a href={receipt.download_url}>Download this reviewed PDF ↓</a></section>}
        {blocked && <div className="notice blocked" role="alert"><strong>Export blocked</strong><span>{demo.verification?.checks[0]?.reason}</span><button onClick={() => setSelected(demo.evidence.find(item => !item.included) || selected)}>Inspect missing source</button></div>}
        {verified && <div className="notice verified"><strong>Source lock verified</strong><span>All required evidence, values, and page pointers are present.</span><button onClick={() => void exportCard()}>Prepare PDF</button></div>}
      </section>
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
