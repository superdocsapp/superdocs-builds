import { useEffect, useState } from 'react';
import { get } from './api';
import type { Country } from './types';

export default function Countries() {
  const [countries, setCountries] = useState<Country[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<Country[]>('/countries').then(setCountries).catch((err) => setError(String(err)));
  }, []);

  if (error) {
    return (
      <main className="integrity">
        <p className="load-error">Could not load countries: {error}</p>
      </main>
    );
  }

  if (!countries) {
    return (
      <main className="integrity">
        <p>Loading countries…</p>
      </main>
    );
  }

  return (
    <main className="integrity">
      <header className="integrity-header">
        <h1>Countries</h1>
      </header>
      <p className="summary">
        {countries.length} configured — adding one is a data file, not a code change.
      </p>

      <section className="countries">
        {countries.map((country) => (
          <div key={country.code} className="country-row">
            <div className="country-id">
              <span className="pack-chip">{country.code}</span>
              <div>
                <div className="country-name">{country.country}</div>
                <div className="country-office">{country.office}</div>
              </div>
            </div>
            <div className="country-lang">{country.language}</div>
            <div className="country-annex">
              <div>{country.annex_summary.legal_instruments} legal instruments</div>
              <div>{country.annex_summary.external_reporting_channels} external reporting channels</div>
              <div className="country-escalation">{country.annex_summary.escalation_tier_1}</div>
            </div>
          </div>
        ))}
      </section>
    </main>
  );
}
