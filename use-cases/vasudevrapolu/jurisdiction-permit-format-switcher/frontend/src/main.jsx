import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = 'http://localhost:8000';

const initial = {
  project_name: 'Sunrise Residence',
  address: '10 Main St',
  city: 'Demo City',
  state: 'TS',
  postal_code: '500001',
  system_kw: 6.4,
  module_count: 16,
  inverter_model: 'INV-X',
  roof_type: 'asphalt-shingle',
  service_amps: 200,
  battery: false,
  owner_name: 'Synthetic Owner',
  contractor_name: 'Synthetic Solar',
  license_number: ''
};

const sampleNarrative =
  'Residential PV project. Synthetic data for evaluation only.';

function App() {
  const [tab, setTab] = useState('permit');
  const [project, setProject] = useState(initial);
  const [jurisdiction, setJurisdiction] = useState('sunvale');
  const [packet, setPacket] = useState(null);
  const [other, setOther] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [run, setRun] = useState(null);

  const update = (k, v) =>
    setProject((p) => ({
      ...p,
      [k]: v
    }));

  async function generate(j = jurisdiction) {
    setLoading(true);
    setError('');

    try {
      const r = await fetch(API + '/api/permit/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          project,
          master_narrative: sampleNarrative,
          jurisdiction_id: j
        })
      });

      if (!r.ok) {
        throw new Error(await r.text());
      }

      const data = await r.json();
      setPacket(data);
      setJurisdiction(j);
      return data;
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function compare() {
    setLoading(true);
    setError('');

    try {
      const a = await generate('sunvale');

      const r = await fetch(API + '/api/permit/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          project,
          master_narrative: sampleNarrative,
          jurisdiction_id: 'ridgefield'
        })
      });

      if (!r.ok) {
        throw new Error(await r.text());
      }

      const b = await r.json();

      setPacket(a);
      setOther(b);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function startAgent() {
    setLoading(true);
    setError('');

    try {
      const r = await fetch(API + '/api/agent/runs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          documents: [
            {
              name: 'plan.txt',
              text:
                'Project: Sunrise Residence\nSystem Size: 6.4 kW\nStatus: Ready'
            },
            {
              name: 'survey.txt',
              text:
                'Project: Sunrise Residence\nRoof Type: asphalt-shingle\nStatus: Ready'
            }
          ],
          rules: [
            {
              id: 'R1',
              statement: 'Document must contain permit',
              severity: 'warning'
            }
          ]
        })
      });

      if (!r.ok) {
        throw new Error(await r.text());
      }

      const d = await r.json();
      const id = d.run_id;

      const checkRun = async () => {
        try {
          const x = await fetch(API + '/api/agent/runs/' + id).then((res) =>
            res.json()
          );

          setRun(x);

          if (
            !['completed', 'waiting_review', 'failed'].includes(x.status)
          ) {
            setTimeout(checkRun, 500);
          }
        } catch (e) {
          setError(e.message);
        }
      };

      await checkRun();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function approveAgent() {
    if (!run?.id) return;

    setLoading(true);
    setError('');

    try {
      const pending = [
        ...(run.state?.conflicts || []),
        ...(run.state?.findings || [])
      ];

      const decisions = pending.map((item) => ({
        id: item.id,
        kind: item.kind,
        approved: true,
        feedback:
          'Reviewed and approved for the synthetic evaluation.'
      }));

      const r = await fetch(
        API + '/api/agent/runs/' + run.id + '/approve',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            decisions
          })
        }
      );

      if (!r.ok) {
        throw new Error(await r.text());
      }

      const data = await r.json();
      setRun(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shell">
      <header>
        <div>
          <span className="eyebrow">
            ROUND 2 · FULL-STACK AI ENGINEER
          </span>

          <h1>Document Engine</h1>

          <p className="muted">
            Synthetic solar permitting workspace · jurisdiction-aware packet
            generation
          </p>
        </div>

        <div className="badge">Review-first</div>
      </header>

      <nav>
        <button
          className={tab === 'permit' ? 'active' : ''}
          onClick={() => setTab('permit')}
        >
          Permit Switcher
        </button>

        <button
          className={tab === 'agent' ? 'active' : ''}
          onClick={() => setTab('agent')}
        >
          Agentic System
        </button>
      </nav>

      {tab === 'permit' ? (
        <main>
          <section className="grid">
            <div className="card form">
              <div className="cardhead">
                <div>
                  <span className="eyebrow">PROJECT RECORD</span>
                  <h2>One source of truth</h2>
                </div>

                <span className="pill">No re-entry</span>
              </div>

              <div className="fields">
                {[
                  ['project_name', 'Project'],
                  ['address', 'Address'],
                  ['city', 'City'],
                  ['state', 'State'],
                  ['postal_code', 'Postal code'],
                  ['system_kw', 'System kW'],
                  ['module_count', 'Modules'],
                  ['inverter_model', 'Inverter'],
                  ['roof_type', 'Roof type'],
                  ['service_amps', 'Service amps'],
                  ['owner_name', 'Owner'],
                  ['contractor_name', 'Contractor'],
                  ['license_number', 'License']
                ].map(([k, l]) => (
                  <label key={k}>
                    {l}

                    <input
                      value={project[k]}
                      onChange={(e) => update(k, e.target.value)}
                    />
                  </label>
                ))}

                <label className="check">
                  <input
                    type="checkbox"
                    checked={project.battery}
                    onChange={(e) =>
                      update('battery', e.target.checked)
                    }
                  />

                  Battery storage
                </label>
              </div>

              <div className="actions">
                <button
                  className="primary"
                  disabled={loading}
                  onClick={() => generate()}
                >
                  {loading ? 'Generating…' : 'Generate packet'}
                </button>

                <button onClick={compare} disabled={loading}>
                  Compare jurisdictions
                </button>
              </div>
            </div>

            <div className="card target">
              <span className="eyebrow">TARGET AUTHORITY</span>

              <h2>Shape the packet</h2>

              <div className="juris">
                <button
                  className={
                    jurisdiction === 'sunvale' ? 'selected' : ''
                  }
                  onClick={() => generate('sunvale')}
                >
                  <b>Sunvale County</b>
                  <span>PV-101 · ELEC-22</span>
                </button>

                <button
                  className={
                    jurisdiction === 'ridgefield' ? 'selected' : ''
                  }
                  onClick={() => generate('ridgefield')}
                >
                  <b>Ridgefield City</b>
                  <span>R-RES · R-FIRE · R-STR</span>
                </button>
              </div>

              {packet && (
                <div className="status">
                  <span className="dot"></span>

                  {packet.superdocs_used
                    ? 'SuperDocs AI connected'
                    : 'Deterministic demo adapter'}

                  <small>Server-side integration</small>
                </div>
              )}
            </div>
          </section>

          {error && <div className="error">{error}</div>}

          {packet && (
            <section className="output">
              <div className="card preview">
                <div className="cardhead">
                  <div>
                    <span className="eyebrow">ASSEMBLED PACKET</span>
                    <h2>{packet.packet_title}</h2>
                  </div>

                  <button
                    onClick={() => {
                      const blob = new Blob([packet.html], {
                        type: 'text/html'
                      });

                      const a = document.createElement('a');

                      a.href = URL.createObjectURL(blob);
                      a.download =
                        packet.jurisdiction_id + '-permit.html';

                      a.click();
                    }}
                  >
                    Export demo HTML
                  </button>
                </div>

                <div
                  className="doc"
                  dangerouslySetInnerHTML={{
                    __html: packet.html
                  }}
                />
              </div>

              <div className="side">
                <div className="card">
                  <span className="eyebrow">BLOCKING GAPS</span>

                  <h2>
                    {packet.gaps.length
                      ? packet.gaps.length
                      : 'No'}{' '}
                    unresolved
                  </h2>

                  {packet.gaps.length ? (
                    packet.gaps.map((g) => (
                      <div className="gap" key={g.code}>
                        <b>
                          {g.code} · {g.label}
                        </b>

                        <p>{g.reason}</p>
                      </div>
                    ))
                  ) : (
                    <p className="success">
                      All declared requirements satisfied.
                    </p>
                  )}
                </div>

                <div className="card">
                  <span className="eyebrow">
                    SUBMISSION CHECKLIST
                  </span>

                  {packet.checklist.map((c, i) => (
                    <div className="checkrow" key={i}>
                      <span>✓</span>

                      <div>
                        <b>{c.label}</b>
                        <small>
                          {c.kind} · {c.status}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}

          {other && (
            <section className="card compare">
              <span className="eyebrow">
                SAME PROJECT · DIFFERENT JURISDICTION
              </span>

              <h2>Output shape changes without re-entry</h2>

              <div className="comparegrid">
                <div>
                  <h3>{packet.jurisdiction_name}</h3>

                  <ul>
                    {packet.forms.map((x) => (
                      <li key={x.id}>
                        {x.id} — {x.label}
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3>{other.jurisdiction_name}</h3>

                  <ul>
                    {other.forms.map((x) => (
                      <li key={x.id}>
                        {x.id} — {x.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>
          )}
        </main>
      ) : (
        <main>
          <section className="card">
            <span className="eyebrow">
              TASK 1 · AGENTIC SYSTEM
            </span>

            <h2>Analyst that never sleeps</h2>

            <p className="muted">
              Watch the resumable pipeline ingest documents, extract
              facts, reconcile conflicts, check rules and stop at the
              human gate.
            </p>

            <button
              className="primary"
              onClick={startAgent}
              disabled={loading}
            >
              {loading ? 'Running…' : 'Run synthetic corpus'}
            </button>

            {run && (
              <div className="agent">
                <div className="timeline">
                  {[
                    'ingest',
                    'extract',
                    'reconcile',
                    'compliance',
                    'plan_update',
                    'review',
                    'commit'
                  ].map((s) => (
                    <div
                      className={
                        run.state.stage_log?.some(
                          (x) => x.stage === s
                        )
                          ? 'done'
                          : ''
                      }
                      key={s}
                    >
                      <span></span>
                      <b>{s}</b>
                    </div>
                  ))}
                </div>

                <div className="agentresult">
                  <b>Status: {run.status}</b>

                  <pre>
                    {JSON.stringify(
                      run.state.deliverable ||
                        run.state.findings ||
                        {},
                      null,
                      2
                    )}
                  </pre>

                  {run.status === 'waiting_review' && (
                    <div className="reviewbox">
                      <h3>Human review required</h3>

                      <p>
                        The agent has paused before commit because
                        one or more findings require a human decision.
                      </p>

                      {[
                        ...(run.state?.conflicts || []),
                        ...(run.state?.findings || [])
                      ].map((item) => (
                        <div className="gap" key={item.id}>
                          <b>{item.id}</b>

                          <p>{item.message}</p>
                        </div>
                      ))}

                      <button
                        className="primary"
                        disabled={loading}
                        onClick={approveAgent}
                      >
                        {loading
                          ? 'Approving…'
                          : 'Approve & Continue'}
                      </button>
                    </div>
                  )}

                  {run.status === 'completed' && (
                    <div className="success">
                      Human review completed. The agent resumed and
                      committed the approved result.
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        </main>
      )}

      <footer>
        Built for the SuperDocs Round 2 engineer task · synthetic data
        only
      </footer>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);