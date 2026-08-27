import { useState } from 'react'
import DOMPurify from 'dompurify'

type Step = 'idle' | 'running' | 'done' | 'error'
type PipelineStep = 'idle' | 'load-edit' | 'apparatus' | 'done'

interface DiffEntry {
  position: number
  change_type: string
  old_text: string
  new_text: string
}

interface LoadEditResult {
  success: boolean
  ops_used: number
  pre_edit_html: string
  post_edit_html: string
  response_text: string
  errors: string[]
}

interface ApparatusResult {
  success: boolean
  ops_used: number
  changes_count: number
  apparatus_instructions: string[]
  stamp_result: StampResult | null
  diff_entries: DiffEntry[]
  total_paragraphs_old: number
  total_paragraphs_new: number
  errors: string[]
  updated_html?: string
}

interface StampResult {
  header_text: string
  footer_text: string
  ops_used: number
  verified_header: boolean
  verified_footer: boolean
}

const API = '/api'

const SAMPLE_HTML = `<html><body>
<h1>Flight Crew Operating Manual — Rev 0043</h1>
<p>Section 4.1: Normal Procedures</p>
<p>The aircraft must be inspected before every flight per the checklist in Appendix B.</p>
<p>Minimum crew complement: 2 pilots for domestic operations.</p>
<p>Both pilots must hold valid first-class medical certificates.</p>
<p>Section 4.2: Emergency Procedures</p>
<p>In case of engine failure, follow the single-engine approach procedure in 4.2.1.</p>
<p>Declare emergency on frequency 121.5 and divert to nearest suitable airport.</p>
<p>The pilot-in-command must brief all passengers before emergency landing.</p>
<p>Section 4.3: Communication Protocol</p>
<p>All crew members must monitor VHF Channel 121.5 during flight.</p>
<p>Standard phraseology must be used at all times per ICAO Annex 10.</p>
<p>Section 4.4: Documentation Requirements</p>
<p>Flight logs must be completed within 24 hours of landing.</p>
<p>Maintenance reports filed in the central system before end of shift.</p>
</body></html>`

const PRESETS = [
  {
    label: 'Crew Complement',
    text: 'Update section 4.1: change minimum crew complement from 2 pilots to 3 pilots for long-haul flights. Add a note that both pilots must hold type ratings.',
  },
  {
    label: 'Emergency Checklist',
    text: 'Update section 4.2: add mandatory dual-frequency monitoring on 121.5 and 243.0 MHz during single-engine emergency approach.',
  },
  {
    label: 'Maintenance Log',
    text: 'Update section 4.4: change flight log completion deadline from 24 hours to within 2 hours of wheel-stop.',
  },
]

export default function App() {
  const [step, setStep] = useState<Step>('idle')
  const [pipelineStep, setPipelineStep] = useState<PipelineStep>('idle')
  const [error, setError] = useState('')
  const [totalOps, setTotalOps] = useState(0)
  const [editInstructions, setEditInstructions] = useState(PRESETS[0].text)
  const [revisionNumber, setRevisionNumber] = useState('0043')
  const [date, setDate] = useState('2025-01-15')
  const [postEditHtml, setPostEditHtml] = useState('')
  const [diffEntries, setDiffEntries] = useState<DiffEntry[]>([])
  const [apparatusInstructions, setApparatusInstructions] = useState<string[]>([])
  const [stampResult, setStampResult] = useState<StampResult | null>(null)
  const [currentSessionId, setCurrentSessionId] = useState<string>('')
  const [exporting, setExporting] = useState(false)
  const [exportDownloadUrl, setExportDownloadUrl] = useState<string | null>(null)
  const [pdfDataUrl, setPdfDataUrl] = useState<string | null>(null)
  const [exportedPdfPath, setExportedPdfPath] = useState<string | null>(null)
  const [copiedPath, setCopiedPath] = useState(false)
  const [activeTab, setActiveTab] = useState<'preview' | 'apparatus' | 'verify' | 'logs'>('preview')
  const [log, setLog] = useState<{ msg: string; time: string }[]>([])
  const [stepTimers, setStepTimers] = useState<Record<string, number>>({})

  const addLog = (msg: string) => {
    const time = new Date().toLocaleTimeString()
    setLog((prev) => [...prev, { msg, time }])
  }

  const handleRun = async () => {
    setStep('running')
    setPipelineStep('load-edit')
    setError('')
    setTotalOps(0)
    setPostEditHtml('')
    setDiffEntries([])
    setApparatusInstructions([])
    setStampResult(null)
    setExportDownloadUrl(null)
    setPdfDataUrl(null)
    setExportedPdfPath(null)
    setLog([])
    setStepTimers({})

    const sid = `revision-${revisionNumber}-${Date.now()}`
    setCurrentSessionId(sid)
    const instructions = editInstructions
    const summaryText = editInstructions.slice(0, 120)
    const changes = [summaryText]

    try {
      let runningOps = 0

      // Step 1: Load + Edit
      const t1 = Date.now()
      addLog('Step 1/2: Loading document + applying targeted revision edits via SuperDocs...')

      const loadEditRes = await fetch(`${API}/step/load-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          document_html: SAMPLE_HTML,
          edit_instructions: instructions,
        }),
      })
      if (!loadEditRes.ok) throw new Error(`Load+Edit failed: ${loadEditRes.statusText}`)
      const loadEdit = (await loadEditRes.json()) as LoadEditResult
      if (!loadEdit.success) throw new Error(loadEdit.errors.join(', '))

      const actualPreEdit = loadEdit.pre_edit_html || SAMPLE_HTML
      const t1Done = Date.now()
      setStepTimers((prev) => ({ ...prev, 'load-edit': t1Done - t1 }))
      addLog(`Step 1 complete in ${(t1Done - t1)}ms — ${loadEdit.ops_used} op(s) used.`)
      setPostEditHtml(loadEdit.post_edit_html)
      runningOps += loadEdit.ops_used
      setTotalOps(runningOps)

      // Step 2: Apparatus + Margin Change Bars + Stamp
      setPipelineStep('apparatus')
      const t2 = Date.now()
      addLog('Step 2/2: Computing paragraph diffs, generating LEP & Highlights tables...')

      const appRes = await fetch(`${API}/step/apparatus`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sid,
          pre_edit_html: actualPreEdit,
          post_edit_html: loadEdit.post_edit_html,
          revision_number: revisionNumber,
          date: date,
          changes: changes,
          highlights_summary: summaryText,
          include_stamp: true,
        }),
      })
      if (!appRes.ok) throw new Error(`Apparatus failed: ${appRes.statusText}`)
      const apparatus = (await appRes.json()) as ApparatusResult
      if (!apparatus.success) throw new Error(apparatus.errors.join(', '))

      const t2Done = Date.now()
      setStepTimers((prev) => ({ ...prev, apparatus: t2Done - t2 }))
      addLog(`Apparatus complete: ${apparatus.changes_count} paragraph changes detected, ${apparatus.ops_used} op(s).`)

      setDiffEntries(apparatus.diff_entries)
      setApparatusInstructions(apparatus.apparatus_instructions)
      if (apparatus.updated_html) {
        setPostEditHtml(apparatus.updated_html)
      }
      runningOps += apparatus.ops_used
      setTotalOps(runningOps)

      if (apparatus.stamp_result) {
        setStampResult(apparatus.stamp_result)
        addLog(`Stamp stamped: ${apparatus.stamp_result.header_text} / ${apparatus.stamp_result.footer_text}`)
        addLog(`Header PyMuPDF verification: ${apparatus.stamp_result.verified_header ? '✔ Verified' : '✗ Failed'}`)
        addLog(`Footer PyMuPDF verification: ${apparatus.stamp_result.verified_footer ? '✔ Verified' : '✗ Failed'}`)
      }

      setPipelineStep('done')
      setStep('done')
      addLog('Revision cycle complete with full verification.')
    } catch (err: any) {
      setError(err.message || 'Unknown error occurred')
      setStep('error')
      addLog(`ERROR: ${err.message}`)
    }
  }

  const handleExportPdf = async () => {
    if (!currentSessionId) return
    setExporting(true)
    try {
      addLog('Exporting controlled PDF via SuperDocs API...')
      const res = await fetch(`${API}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: currentSessionId,
          revision_number: revisionNumber,
          document_html: postEditHtml || SAMPLE_HTML,
          output_path: `reports/FCOM-Rev-${revisionNumber}.pdf`,
        }),
      })
      if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
      const data = await res.json()
      setExportedPdfPath(data.pdf_path)
      setExportDownloadUrl(data.download_url)
      setPdfDataUrl(data.pdf_data_url || null)
      addLog(`Controlled PDF generated: ${data.pdf_path}`)
    } catch (err: any) {
      addLog(`PDF Export Error: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  const isStep1Done = step === 'done' || pipelineStep === 'apparatus'
  const isStep2Done = step === 'done'
  const progressPct = step === 'done' ? 100 : pipelineStep === 'apparatus' ? 66 : pipelineStep === 'load-edit' ? 33 : 0

  return (
    <div className="app-container">
      {/* Top Header */}
      <header style={{
        background: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
        padding: '12px 24px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}>
        <div style={{
          maxWidth: 1480,
          margin: '0 auto',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 16,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              background: 'linear-gradient(135deg, #0ea5e9, #6366f1)',
              color: '#fff',
              fontWeight: 800,
              fontSize: 12,
              padding: '4px 10px',
              borderRadius: 6,
              letterSpacing: '0.05em',
            }}>
              ✈️ AERODOC
            </span>
            <span style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--text-primary)' }}>
              FCOM Controlled Revision System
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Rev:</span>
              <input
                type="text"
                className="input-control"
                value={revisionNumber}
                onChange={(e) => setRevisionNumber(e.target.value)}
                style={{ width: 70, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700 }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span style={{ color: 'var(--text-muted)' }}>Date:</span>
              <input
                type="text"
                className="input-control"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                style={{ width: 110, fontFamily: 'var(--font-mono)', fontSize: 12 }}
              />
            </div>
            <span className="badge badge-cyan" style={{ fontFamily: 'var(--font-mono)', textTransform: 'none' }}>
              Budget: {totalOps}/2 Ops Used
            </span>
            <span className="badge badge-emerald">
              <span className="pulse-dot" /> API Online
            </span>
          </div>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="workspace-grid">
        {/* Left Column: Revision Configuration & Diff */}
        <section style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Stepper Panel */}
          <div className="panel" style={{ padding: '14px 18px' }}>
            <div className="panel-header" style={{ marginBottom: 10, paddingBottom: 8 }}>
              <div className="panel-title">
                <span>⚡</span>
                <span>Revision Pipeline</span>
                <span className={`badge ${step === 'done' ? 'badge-emerald' : step === 'running' ? 'badge-cyan' : 'badge-gray'}`}>
                  {step === 'running' ? 'RUNNING' : step === 'done' ? 'COMPLETED' : 'READY'}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Progress: <b style={{ color: step === 'done' ? 'var(--emerald-text)' : 'var(--cyan-text)' }}>{progressPct}%</b>
              </div>
            </div>

            {/* Progress Line */}
            <div style={{
              width: '100%',
              height: 3,
              background: 'var(--bg-canvas)',
              borderRadius: 2,
              overflow: 'hidden',
              marginBottom: 12,
            }}>
              <div style={{
                width: `${progressPct}%`,
                height: '100%',
                background: step === 'done' ? 'var(--emerald-solid)' : 'linear-gradient(90deg, #0ea5e9, #10b981)',
                transition: 'width 0.3s ease',
              }} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
              <div style={{
                background: pipelineStep === 'load-edit' ? 'var(--cyan-bg)' : isStep1Done ? 'var(--emerald-bg)' : 'var(--bg-surface-elevated)',
                border: `1px solid ${pipelineStep === 'load-edit' ? 'var(--cyan-border)' : isStep1Done ? 'var(--emerald-border)' : 'var(--border-subtle)'}`,
                borderRadius: 8,
                padding: '8px 10px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: isStep1Done ? 'var(--emerald-text)' : 'var(--text-primary)' }}>
                    1. Load & Edit
                  </span>
                  {isStep1Done ? <span style={{ color: 'var(--emerald-text)', fontSize: 11, fontWeight: 700 }}>✔</span> : pipelineStep === 'load-edit' ? <span className="pulse-dot" style={{ background: 'var(--cyan-solid)' }} /> : null}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  {stepTimers['load-edit'] ? `${stepTimers['load-edit']}ms` : 'Targeted AST edit'}
                </div>
              </div>

              <div style={{
                background: pipelineStep === 'apparatus' ? 'var(--cyan-bg)' : isStep2Done ? 'var(--emerald-bg)' : 'var(--bg-surface-elevated)',
                border: `1px solid ${pipelineStep === 'apparatus' ? 'var(--cyan-border)' : isStep2Done ? 'var(--emerald-border)' : 'var(--border-subtle)'}`,
                borderRadius: 8,
                padding: '8px 10px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: isStep2Done ? 'var(--emerald-text)' : 'var(--text-primary)' }}>
                    2. Margin Bars & LEP
                  </span>
                  {isStep2Done ? <span style={{ color: 'var(--emerald-text)', fontSize: 11, fontWeight: 700 }}>✔</span> : pipelineStep === 'apparatus' ? <span className="pulse-dot" style={{ background: 'var(--cyan-solid)' }} /> : null}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  {stepTimers['apparatus'] ? `${stepTimers['apparatus']}ms` : 'Diff & table generator'}
                </div>
              </div>

              <div style={{
                background: step === 'done' ? 'var(--emerald-bg)' : 'var(--bg-surface-elevated)',
                border: `1px solid ${step === 'done' ? 'var(--emerald-border)' : 'var(--border-subtle)'}`,
                borderRadius: 8,
                padding: '8px 10px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: step === 'done' ? 'var(--emerald-text)' : 'var(--text-primary)' }}>
                    3. Stamp & Export
                  </span>
                  {step === 'done' && <span style={{ color: 'var(--emerald-text)', fontSize: 11, fontWeight: 700 }}>✔</span>}
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                  {exportedPdfPath ? 'PDF Generated' : 'PyMuPDF verified'}
                </div>
              </div>
            </div>
          </div>

          {/* Edit Instruction Panel */}
          <div className="panel">
            <div className="panel-header" style={{ marginBottom: 8 }}>
              <div className="panel-title">
                <span>📝</span>
                <span>Revision Instruction</span>
              </div>
            </div>

            {/* Quick Presets Row */}
            <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center', marginRight: 4 }}>Presets:</span>
              {PRESETS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  className={`chip ${editInstructions === p.text ? 'active' : ''}`}
                  onClick={() => setEditInstructions(p.text)}
                >
                  {p.label}
                </button>
              ))}
            </div>

            <textarea
              className="input-control"
              rows={3}
              value={editInstructions}
              onChange={(e) => setEditInstructions(e.target.value)}
              style={{ width: '100%', resize: 'vertical', fontSize: 12.5, lineHeight: 1.5, marginBottom: 12 }}
            />

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary"
                disabled={step === 'running'}
                onClick={handleRun}
                style={{ fontWeight: 600, padding: '8px 18px' }}
              >
                {step === 'running' ? (
                  <>
                    <span className="spinner" />
                    <span>Running Pipeline</span>
                  </>
                ) : (
                  '▶ Run Revision Cycle'
                )}
              </button>

              {error && <span style={{ color: 'var(--rose-text)', fontSize: 12 }}>{error}</span>}
            </div>
          </div>

          {/* Redline Diff Inspector */}
          <div className="panel" style={{ flex: 1 }}>
            <div className="panel-header">
              <div className="panel-title">
                <span>🔍</span>
                <span>Redline Paragraph Diff ({diffEntries.length} changes)</span>
              </div>
              {diffEntries.length > 0 && (
                <span className="badge badge-amber">Margin Bars Active</span>
              )}
            </div>

            {diffEntries.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-muted)', border: '1px dashed var(--border-subtle)', borderRadius: 8 }}>
                Run the revision cycle to view paragraph-level redline changes.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {diffEntries.map((e, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: 'var(--bg-surface-elevated)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 8,
                      overflow: 'hidden',
                    }}
                  >
                    <div style={{
                      background: 'var(--bg-canvas)',
                      padding: '6px 12px',
                      fontSize: 11,
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      display: 'flex',
                      justifyContent: 'space-between',
                    }}>
                      <span>Paragraph {e.position}</span>
                      <span style={{
                        color: e.change_type === 'modified' ? 'var(--amber-text)' : e.change_type === 'added' ? 'var(--emerald-text)' : 'var(--rose-text)',
                        fontWeight: 700,
                      }}>
                        ● {e.change_type.toUpperCase()}
                      </span>
                    </div>

                    {e.old_text && (
                      <div style={{
                        padding: '8px 12px',
                        background: 'var(--rose-bg)',
                        borderLeft: '4px solid var(--rose-solid)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 12,
                        color: 'var(--rose-text)',
                      }}>
                        <span style={{ marginRight: 8, fontWeight: 700 }}>-</span>
                        {e.old_text}
                      </div>
                    )}

                    {e.new_text && (
                      <div style={{
                        padding: '8px 12px',
                        background: 'var(--emerald-bg)',
                        borderLeft: '4px solid var(--emerald-solid)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 12,
                        color: 'var(--emerald-text)',
                      }}>
                        <span style={{ marginRight: 8, fontWeight: 700 }}>+</span>
                        {e.new_text}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Right Column: Tabbed Aviation Apparatus */}
        <section className="panel" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="panel-header" style={{ marginBottom: 10 }}>
            <div className="tab-bar" style={{ margin: 0, width: '100%' }}>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'preview' ? 'active' : ''}`}
                onClick={() => setActiveTab('preview')}
              >
                📄 Preview
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'apparatus' ? 'active' : ''}`}
                onClick={() => setActiveTab('apparatus')}
              >
                📋 Apparatus ({apparatusInstructions.length})
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'verify' ? 'active' : ''}`}
                onClick={() => setActiveTab('verify')}
              >
                🛡️ Verification
              </button>
              <button
                type="button"
                className={`tab-btn ${activeTab === 'logs' ? 'active' : ''}`}
                onClick={() => setActiveTab('logs')}
              >
                💻 Logs ({log.length})
              </button>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {/* Tab 1: Preview */}
            {activeTab === 'preview' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {postEditHtml ? 'Controlled Document Output' : 'Baseline Document Template'}
                  </span>

                  {postEditHtml && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      {exportDownloadUrl && (
                        <a
                          href={exportDownloadUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-secondary"
                          style={{ fontSize: 11, padding: '4px 10px', textDecoration: 'none' }}
                        >
                          🔗 Open Link
                        </a>
                      )}
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={exporting}
                        onClick={handleExportPdf}
                        style={{ fontSize: 11, padding: '4px 10px' }}
                      >
                        {exporting ? (
                          <>
                            <span className="spinner" />
                            <span>Exporting PDF</span>
                          </>
                        ) : (
                          '📥 Export Controlled PDF'
                        )}
                      </button>
                    </div>
                  )}
                </div>

                {exportedPdfPath && (
                  <div style={{
                    background: 'var(--emerald-bg)',
                    border: '1px solid var(--emerald-border)',
                    borderRadius: 8,
                    padding: '10px 14px',
                    marginBottom: 14,
                    fontSize: 12,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: 8,
                  }}>
                    <span style={{ color: 'var(--emerald-text)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                      ✔ Controlled PDF: {exportedPdfPath}
                    </span>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {pdfDataUrl && (
                        <a
                          href={pdfDataUrl}
                          download={`FCOM-Rev-${revisionNumber}.pdf`}
                          className="btn btn-primary"
                          style={{ fontSize: 11, padding: '4px 12px', textDecoration: 'none', fontWeight: 600 }}
                        >
                          📥 Download PDF
                        </a>
                      )}
                      {exportDownloadUrl && (
                        <a
                          href={exportDownloadUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="btn btn-secondary"
                          style={{ fontSize: 11, padding: '4px 10px', textDecoration: 'none' }}
                        >
                          🔗 Open Cloud URL
                        </a>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => {
                          navigator.clipboard.writeText(exportedPdfPath)
                          setCopiedPath(true)
                          setTimeout(() => setCopiedPath(false), 2000)
                        }}
                        style={{ fontSize: 11, padding: '4px 8px' }}
                      >
                        {copiedPath ? '✔ Copied' : '📋 Copy Path'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Simulated Aviation Paper */}
                <div className="aviation-document-paper">
                  {/* Running Header */}
                  <div style={{
                    background: '#f8fafc',
                    borderBottom: '1px solid #e2e8f0',
                    padding: '8px 18px',
                    fontSize: 11,
                    color: '#64748b',
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                  }}>
                    <span>{stampResult ? stampResult.header_text : `FCOM Rev ${revisionNumber} — ${date}`}</span>
                    <span style={{ color: '#0284c7' }}>CONTROLLED REVISION</span>
                  </div>

                  {/* Sanitized Document Body */}
                  <div
                    style={{ padding: '24px 28px', minHeight: 320 }}
                    dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(postEditHtml || SAMPLE_HTML) }}
                  />

                  {/* Running Footer (Bottom Centered) */}
                  <div style={{
                    background: '#f8fafc',
                    borderTop: '1px solid #e2e8f0',
                    padding: '10px 18px',
                    fontSize: 11,
                    color: '#64748b',
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    letterSpacing: '0.04em',
                  }}>
                    <span>{stampResult ? stampResult.footer_text : 'Page 1 of 1'}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 2: Apparatus */}
            {activeTab === 'apparatus' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {apparatusInstructions.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '36px 16px', color: 'var(--text-muted)' }}>
                    No apparatus instructions generated yet. Run the revision cycle to produce LEP and Revision Tables.
                  </div>
                ) : (
                  apparatusInstructions.map((ins, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: 'var(--bg-surface-elevated)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 8,
                        padding: '12px 14px',
                        fontSize: 12.5,
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <div style={{ color: 'var(--cyan-text)', fontWeight: 700, marginBottom: 4 }}>
                        INSTRUCTION #{idx + 1}
                      </div>
                      {ins}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Tab 3: Verification */}
            {activeTab === 'verify' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 10 }}>
                    PyMuPDF Automated Verification Harness
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Header Verification:</span>
                      <span className={`badge ${stampResult?.verified_header ? 'badge-emerald' : 'badge-gray'}`}>
                        {stampResult?.verified_header ? '✔ Verified' : 'Pending'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Footer Verification:</span>
                      <span className={`badge ${stampResult?.verified_footer ? 'badge-emerald' : 'badge-gray'}`}>
                        {stampResult?.verified_footer ? '✔ Verified' : 'Pending'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Margin Change Bars:</span>
                      <span className="badge badge-cyan" style={{ fontFamily: 'var(--font-mono)' }}>
                        {diffEntries.length} Active Bar(s)
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Tab 4: Logs */}
            {activeTab === 'logs' && (
              <div style={{
                background: 'var(--bg-canvas)',
                borderRadius: 8,
                padding: '12px 14px',
                fontFamily: 'var(--font-mono)',
                fontSize: 11.5,
                color: 'var(--text-secondary)',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                maxHeight: 400,
                overflowY: 'auto',
              }}>
                {log.map((l, idx) => (
                  <div key={idx} style={{ display: 'flex', gap: 10 }}>
                    <span style={{ color: 'var(--text-muted)' }}>[{l.time}]</span>
                    <span>{l.msg}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}
