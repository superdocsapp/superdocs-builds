import { useEffect, useState } from 'react';
import { get, post } from './api';
import type { Country, RunDetail, RunLedger, RunSummary } from './types';

const POLL_INTERVAL_MS = 1500;

export default function Generate() {
  const [countries, setCountries] = useState<Country[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState('');
  const [error, setError] = useState<string | null>(null);

  const [run, setRun] = useState<RunSummary | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [ledger, setLedger] = useState<RunLedger | null>(null);

  useEffect(() => {
    get<Country[]>('/countries').then(setCountries).catch((err) => setError(String(err)));
  }, []);

  // Poll while the run is still in flight — a rollout can legitimately
  // take minutes per country, so this keeps the ledger visibly growing
  // rather than making the user wait on one blocking request.
  useEffect(() => {
    if (!run || run.status === 'done' || run.status === 'error') return;
    const id = setInterval(async () => {
      try {
        const [d, l] = await Promise.all([
          get<RunDetail>(`/runs/${run.run_id}`),
          get<RunLedger>(`/runs/${run.run_id}/ledger`),
        ]);
        setDetail(d);
        setLedger(l);
        if (d.status === 'done' || d.status === 'error') {
          setRun(d);
        }
      } catch (err) {
        setError(String(err));
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [run]);

  function toggle(code: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }

  async function startRollout() {
    setError(null);
    setDetail(null);
    setLedger(null);
    try {
      const started = await post<RunSummary>('/runs/rollout', {
        countries: Array.from(selected),
        limit: limit ? Number(limit) : null,
      });
      setRun(started);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <main className="integrity">
      <header className="integrity-header">
        <h1>Generate</h1>
      </header>
      <p className="summary">Lock the core, then generate a pack per selected country.</p>

      <section className="generate-form">
        <h2>Countries</h2>
        {!countries && <p>Loading countries…</p>}
        {countries && (
          <div className="generate-checkboxes">
            {countries.map((c) => (
              <label key={c.code} className="generate-checkbox">
                <input type="checkbox" checked={selected.has(c.code)} onChange={() => toggle(c.code)} />
                <span className="pack-chip">{c.code}</span>
                {c.country}
              </label>
            ))}
          </div>
        )}

        <div className="generate-controls">
          <label className="generate-limit">
            Limit
            <input
              type="number"
              min={1}
              placeholder="all selected"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="generate-run"
            disabled={selected.size === 0 || (run !== null && run.status !== 'done' && run.status !== 'error')}
            onClick={startRollout}
          >
            Run rollout
          </button>
        </div>

        {error && <p className="load-error">{error}</p>}
      </section>

      {run && (
        <section className="run-status">
          <h2>Run</h2>
          <div className="run-status-row">
            <code>{run.run_id}</code>
            <span className={`status-badge ${run.status === 'error' ? 'fail' : run.status === 'done' ? 'pass' : ''}`}>
              {run.status.toUpperCase()}
            </span>
          </div>
          {detail?.error && <p className="load-error">{detail.error}</p>}
        </section>
      )}

      {ledger && (
        <section className="ledger">
          <h2>Ledger — live</h2>
          <p>What this run has spent so far, step by step.</p>
          {ledger.entries.length === 0 && <p>No operations charged yet.</p>}
          {ledger.entries.map((entry, i) => (
            <div key={i} className="ledger-row">
              <div className="ledger-step">[{entry.step}]</div>
              <div className="ledger-subject">{entry.subject}</div>
              <div className="ledger-ops">
                {entry.status === 'SKIPPED' ? 'SKIPPED ' : ''}
                {entry.operations} op{entry.operations === 1 ? '' : 's'}
              </div>
            </div>
          ))}
          <div className="ledger-row ledger-total">
            <div className="ledger-step" />
            <div className="ledger-subject">total</div>
            <div className="ledger-ops">
              {ledger.total_operations} op{ledger.total_operations === 1 ? '' : 's'}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
