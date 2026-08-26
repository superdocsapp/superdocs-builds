import { useCallback, useEffect, useState } from 'react'
import {
  getJson,
  postGenerate,
  type LedgerSnapshot,
  type RunRecord,
} from './api'
import './Generate.css'

const VERTICALS = ['legal', 'fintech', 'healthcare', 'edtech', 'all'] as const

type Props = {
  snapshot: LedgerSnapshot
}

function fmtWall(s: number): string {
  if (!Number.isFinite(s)) return '—'
  if (s < 10) return `${s.toFixed(2)}s`
  return `${Math.round(s)}s`
}

export default function Generate({ snapshot }: Props) {
  const [vertical, setVertical] = useState<string>('legal')
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [run, setRun] = useState<RunRecord | null>(null)
  const [ledger, setLedger] = useState<LedgerSnapshot>(snapshot)
  const [live, setLive] = useState(false)

  const refreshLedger = useCallback(async () => {
    try {
      const next = await getJson<LedgerSnapshot>('/ledger')
      setLedger(next)
      setLive(true)
    } catch {
      setLedger(snapshot)
      setLive(false)
    }
  }, [snapshot])

  useEffect(() => {
    void refreshLedger()
    const id = window.setInterval(() => void refreshLedger(), 2500)
    return () => window.clearInterval(id)
  }, [refreshLedger])

  useEffect(() => {
    if (!run?.run_id && !run?.status) return
    if (run.status === 'done' || run.status === 'error') return
    const pollId = run.run_id
    if (!pollId) return
    const id = window.setInterval(() => {
      void getJson<RunRecord>(`/runs/${pollId}`)
        .then(setRun)
        .catch((err: Error) =>
          setRun((prev) =>
            prev ? { ...prev, status: 'error', error: err.message } : prev,
          ),
        )
    }, 2000)
    return () => window.clearInterval(id)
  }, [run?.run_id, run?.status])

  async function onQueue() {
    setBusy(true)
    setNotice(null)
    try {
      const queued = await postGenerate(vertical, force)
      setRun({
        run_id: queued.run_id,
        status: queued.status,
        vertical: queued.vertical,
      })
      setNotice(`Queued ${queued.vertical} · poll ${queued.poll}`)
    } catch (err) {
      setNotice(
        err instanceof Error
          ? `${err.message} — start uvicorn on :8000; Vite proxies /api.`
          : 'generate failed',
      )
    } finally {
      setBusy(false)
    }
  }

  const reversed = [...ledger.entries].reverse()

  return (
    <main className="div">
      <p className="div-kicker">ClarityDocs · speaking scripts · not a slide deck</p>
      <p className="div-verdict div-verdict-pass">202 then poll</p>
      <h1 className="div-title">Generate</h1>
      <p className="div-lede">
        Queue a vertical. The request returns immediately. SuperDocs work is
        backgrounded. The ledger is the live cost of that work.
      </p>
      <p className="div-rule">
        Idempotent unless force is set. Batch cap 2. {live ? 'Live ledger from the API.' : 'API unreachable — showing the committed four-vertical snapshot.'}
      </p>

      <section className="gen-form" aria-label="Queue generation">
        <label className="gen-label">
          Vertical
          <select
            className="gen-select"
            value={vertical}
            onChange={(e) => setVertical(e.target.value)}
          >
            {VERTICALS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="gen-check">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
          />
          Force regenerate
        </label>
        <button className="gen-btn" type="button" disabled={busy} onClick={() => void onQueue()}>
          {busy ? 'Queuing…' : 'Queue generate'}
        </button>
        {notice ? <p className="gen-notice">{notice}</p> : null}
        {run ? (
          <p className="gen-run">
            Run {run.run_id ?? '—'} · {run.status}
            {run.error ? ` · ${run.error}` : ''}
          </p>
        ) : null}
      </section>

      <section className="div-means" aria-label="Operations charged">
        <article className="div-mean">
          <p className="div-mean-label">Operations</p>
          <p className="div-mean-value">{ledger.total_operations}</p>
          <p className="div-mean-note">
            {live ? 'Live' : 'Snapshot'} · {ledger.entries.length} steps.
          </p>
        </article>
        <article className="div-mean">
          <p className="div-mean-label">Source</p>
          <p className="gen-source">
            {ledger.source ?? 'empty ledger'}
          </p>
          <p className="div-mean-note">
            Chat batches bill. Export and score do not.
          </p>
        </article>
      </section>

      <section className="div-grid-wrap" aria-label="Ledger entries">
        <h2 className="div-grid-title">Ledger</h2>
        <table className="div-grid">
          <thead>
            <tr>
              <th scope="col">Step</th>
              <th scope="col">Vertical</th>
              <th scope="col">Ops</th>
              <th scope="col">Wall</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {reversed.map((e) => (
              <tr key={e.content_key}>
                <th scope="row">{e.step}</th>
                <td className="div-weight">{e.vertical}</td>
                <td className="div-cell">{e.operations}</td>
                <td className="div-cell">{fmtWall(e.wall_time)}</td>
                <td className="div-cell">{e.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  )
}
