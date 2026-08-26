import { useEffect, useState } from 'react';
import type { IntegrityReport } from './types';

// First 12 + last 6 characters — enough to eyeball-compare two hashes
// without reading 64 characters, full value always in `title` on hover.
function truncateHash(hash: string): string {
  if (hash.length <= 22) return hash;
  return `${hash.slice(0, 12)}…${hash.slice(-6)}`;
}

export default function Integrity() {
  const [report, setReport] = useState<IntegrityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/integrity-report.json')
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json() as Promise<IntegrityReport>;
      })
      .then(setReport)
      .catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <main className="integrity">
        <p className="load-error">Could not load the integrity report: {error}</p>
      </main>
    );
  }

  if (!report) {
    return (
      <main className="integrity">
        <p>Loading integrity report…</p>
      </main>
    );
  }

  const languages = Object.entries(report.core_identity);
  const languageCounts = Object.entries(report.languages)
    .map(([lang, count]) => `${lang} ${count}`)
    .join(' · ');

  return (
    <main className="integrity">
      <header className="integrity-header">
        <h1>Core Integrity</h1>
        <span className={`status-badge ${report.all_packs_pass ? 'pass' : 'fail'}`}>
          {report.all_packs_pass ? 'ALL PACKS PASS' : 'FAILING'}
        </span>
      </header>

      <p className="summary">
        Core v{report.core_version} · {report.packs} packs · {languageCounts}
      </p>

      {report.quarantined_packs && report.quarantined_packs.length > 0 && (
        <section className="quarantine">
          <h2>Quarantined</h2>
          <p>
            Failed verification and were never shipped — a hash mismatch quarantines the pack;
            it is not counted above and does not reach an office.
          </p>
          <div className="quarantine-packs">
            {report.quarantined_packs.map((code) => (
              <span key={code} className="pack-chip quarantine-chip">
                {code}
              </span>
            ))}
          </div>
        </section>
      )}

      <section className="identity">
        <h2>Core identity, per language</h2>
        {languages.map(([lang, entry]) => (
          <div key={lang} className={`identity-row ${entry.identical ? 'identical' : 'divergent'}`}>
            <div className="identity-lang">{lang}</div>
            <div className="identity-hash" title={entry.expected}>
              {truncateHash(entry.expected)}
            </div>
            <div className="identity-packs">
              {entry.packs.map((code) => (
                <span key={code} className="pack-chip">
                  {code}
                </span>
              ))}
            </div>
            <div className="identity-state">{entry.identical ? 'IDENTICAL' : 'DIVERGENT'}</div>
          </div>
        ))}
      </section>

      <section className="divergence">
        <h2>Annex divergence</h2>
        <p>Counted, not claimed — how many distinct values exist per slot across every pack.</p>
        {Object.entries(report.annex_divergence).map(([slot, count]) => (
          <div key={slot} className="divergence-row">
            <div className="divergence-slot">{slot}</div>
            <div className="divergence-count">{count}</div>
          </div>
        ))}
      </section>
    </main>
  );
}
