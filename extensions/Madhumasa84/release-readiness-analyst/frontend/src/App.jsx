import { useEffect, useMemo, useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`)
  return body
}

export default function App() {
  const [workspace, setWorkspace] = useState('demo-workspace')
  const [title, setTitle] = useState('Q3 release readiness')
  const [run, setRun] = useState(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [decisions, setDecisions] = useState({})
  const required = useMemo(() => (run?.findings || []).filter((finding) => finding.decision_required), [run])

  async function createRun() {
    setBusy(true); setError('')
    try { setRun(await request('/runs', { method: 'POST', body: JSON.stringify({ workspace_id: workspace, title }) })) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function uploadAndRun() {
    if (!selectedFile || !run?.id) return
    setBusy(true); setError('')
    try {
      const form = new FormData(); form.append('file', selectedFile)
      const uploaded = await fetch(`${API}/runs/${run.id}/sources`, { method: 'POST', body: form })
      if (!uploaded.ok) throw new Error((await uploaded.json()).detail)
      setRun(await request(`/runs/${run.id}/execute`, { method: 'POST' }))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  async function submitDecisions() {
    setBusy(true); setError('')
    try {
      const payload = required.filter((finding) => decisions[finding.id]).map((finding) => ({ finding_id: finding.id, state: decisions[finding.id], feedback: null }))
      setRun(await request(`/runs/${run.id}/decisions`, { method: 'POST', body: JSON.stringify({ decisions: payload }) }))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  useEffect(() => {
    if (!run?.id) return undefined
    const timer = setInterval(() => request(`/runs/${run.id}`).then(setRun).catch(() => {}), 2500)
    return () => clearInterval(timer)
  }, [run?.id])

  return <main className="shell">
    <header><p className="eyebrow">RELEASE READINESS ANALYST</p><h1>Evidence you can defend.</h1><p className="lede">Turn release artifacts into a cited verdict, with every blocker and decision visible.</p></header>
    <section className="card setup"><div><label>Workspace<input value={workspace} onChange={(event) => setWorkspace(event.target.value)} /></label><label>Run title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label></div><button disabled={busy} onClick={createRun}>Create run</button></section>
    {run && <section className="card"><div className="run-head"><div><span className="eyebrow">{run.status}</span><h2>{run.title || title}</h2><p className="muted">{run.id}</p></div><label className="upload">Add source<input type="file" onChange={(event) => setSelectedFile(event.target.files[0])} /></label><button disabled={busy || !selectedFile} onClick={uploadAndRun}>Analyze</button></div><div className="stages">{['parse_sources','extract_requirements','map_evidence','analyze_contradictions','evaluate_release_rules','draft_report'].map((stage) => <span className={run.current_stage === stage ? 'stage active' : 'stage'} key={stage}>{stage.replaceAll('_', ' ')}</span>)}</div></section>}
    {error && <div className="error" role="alert">{error}</div>}
    {run?.findings?.length > 0 && <section className="grid">{run.findings.map((finding) => <article className={`card finding ${finding.severity}`} key={finding.id}><div className="finding-top"><span className="tag">{finding.severity}</span><span className="muted">{finding.kind}</span></div><h3>{finding.title}</h3><p>{finding.summary}</p>{finding.citations?.map((citation) => <blockquote key={`${citation.source_id}-${citation.locator.line_start}`}><strong>{citation.filename}</strong> · line {citation.locator.line_start}<br />“{citation.quote}”</blockquote>)}{finding.decision_required && <select value={decisions[finding.id] || ''} onChange={(event) => setDecisions({ ...decisions, [finding.id]: event.target.value })}><option value="">Choose decision</option><option value="approved">Approve</option><option value="rejected">Reject</option><option value="more_evidence">Request more evidence</option></select>}</article>)}</section>}
    {required.length > 0 && <button className="primary" disabled={busy || required.some((finding) => !decisions[finding.id])} onClick={submitDecisions}>Submit item decisions</button>}
    {run?.report && <section className="card report"><div className="run-head"><h2>Readiness brief</h2><span className="tag">{run.report.verdict}</span></div><p>{run.report.findings.length} cited findings · {run.metrics?.length || 0} completed stages</p><pre>{JSON.stringify(run.report, null, 2)}</pre></section>}
  </main>
}
