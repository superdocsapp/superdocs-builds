import { useEffect, useState } from 'react';
import { get, post } from './api';
import type { AmendmentResult, Country, RunDetail, RunLedger, RunSummary } from './types';

const POLL_INTERVAL_MS = 1500;

export default function Amend() {
  const [countries, setCountries] = useState<Country[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const [run, setRun] = useState<RunSummary | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [ledger, setLedger] = useState<RunLedger | null>(null);

  useEffect(() => {
    get<Country[]>('/countries').then(setCountries).catch((err) => setError(String(err)));
  }, []);

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
        if (d.status === 'done' || d.status === 'error') setRun(d);
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

  async function startAmendment() {
    setError(null);
    setDetail(null);
    setLedger(null);
    try {
      const started = await post<RunSummary>('/runs/amendment', { countries: Array.from(selected) });
      setRun(started);
    } catch (err) {
      setError(String(err));
    }
  }

  const result = detail?.result as unknown as AmendmentResult | undefined;

  return (
    <main className="integrity">
      <header className="integrity-header">
        <h1>Amend</h1>
      </header>
      <p className="summary">
        Re-lock the core, then send each selected country its own change notice — zero packs
        are reissued.
      </p>

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
          <button
            type="button"
            className="generate-run"
            disabled={selected.size === 0 || (run !== null && run.status !== 'done' && run.status !== 'error')}
            onClick={startAmendment}
          >
            Run amendment
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

      {result && (
        <>
          <section className="diff">
            <h2>Core diff</h2>
            <p>
              v{result.diff.from_version} → v{result.diff.to_version} · section
              {result.diff.changed_sections.length === 1 ? '' : 's'} {result.diff.changed_sections.join(', ') || '—'}{' '}
              changed of {result.diff.core_sections_total}. Section
              {result.diff.unchanged_sections.length === 1 ? '' : 's'} {result.diff.unchanged_sections.join(', ')}{' '}
              unchanged.
            </p>
          </section>

          <section className="verification">
            <h2>Verification</h2>
            <div className="verify-row">
              <span>Every pack still passes, unreissued</span>
              <span className={`status-badge ${result.verification.all_packs_pass ? 'pass' : 'fail'}`}>
                {result.verification.all_packs_pass ? 'PASS' : 'FAIL'}
              </span>
            </div>
            <div className="verify-row">
              <span>Annexes untouched</span>
              <span className={`status-badge ${result.verification.all_annexes_untouched ? 'pass' : 'fail'}`}>
                {result.verification.all_annexes_untouched ? 'PASS' : 'FAIL'}
              </span>
            </div>
            <div className="verify-row">
              <span>v2 core identity consistent across languages</span>
              <span className={`status-badge ${result.verification.all_v2_identity_consistent ? 'pass' : 'fail'}`}>
                {result.verification.all_v2_identity_consistent ? 'PASS' : 'FAIL'}
              </span>
            </div>
          </section>

          <section className="notices">
            <h2>Change notices</h2>
            {Object.entries(result.notices).map(([code, notice]) => (
              <div key={code} className="notice-row">
                <span className="pack-chip">{code}</span>
                <span className="notice-status">{notice.skipped ? 'already sent' : 'sent'}</span>
                <a
                  href={`/api/exports/${code}/change-notice-v${result.diff.from_version}-v${result.diff.to_version}.md`}
                  target="_blank"
                  rel="noreferrer"
                >
                  .md
                </a>
              </div>
            ))}
          </section>
        </>
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
