import { useEffect, useState } from 'react';
import { get } from './api';
import type { PackSummary } from './types';

function truncateHash(hash: string): string {
  if (hash.length <= 22) return hash;
  return `${hash.slice(0, 12)}…${hash.slice(-6)}`;
}

export default function Packs() {
  const [packs, setPacks] = useState<PackSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<PackSummary[]>('/packs').then(setPacks).catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <main className="integrity">
        <p className="load-error">Could not load packs: {error}</p>
      </main>
    );
  }

  if (!packs) {
    return (
      <main className="integrity">
        <p>Loading packs…</p>
      </main>
    );
  }

  const generatedCount = packs.filter((p) => p.generated).length;

  return (
    <main className="integrity">
      <header className="integrity-header">
        <h1>Packs</h1>
      </header>
      <p className="summary">
        {generatedCount} of {packs.length} generated
      </p>

      <section className="packs">
        {packs.map((pack) => (
          <div key={pack.code} className={`pack-row ${pack.generated ? 'generated' : 'pending'}`}>
            <div className="pack-id">
              <span className="pack-chip">{pack.code}</span>
              {pack.country}
            </div>
            {pack.generated && pack.core_hash ? (
              <>
                <div className="pack-hash" title={pack.core_hash}>
                  {truncateHash(pack.core_hash)}
                </div>
                <div className="pack-exports">
                  {pack.exports && (
                    <>
                      <a href={`/api${pack.exports.markdown}`} target="_blank" rel="noreferrer">
                        .md
                      </a>
                      <a href={`/api${pack.exports.docx}`} target="_blank" rel="noreferrer">
                        .docx
                      </a>
                    </>
                  )}
                </div>
              </>
            ) : (
              <div className="pack-not-generated">not generated</div>
            )}
          </div>
        ))}
      </section>
    </main>
  );
}
