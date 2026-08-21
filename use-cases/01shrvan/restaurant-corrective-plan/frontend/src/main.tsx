import * as React from 'react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, Download, Loader2, Plus, Stamp, Trash2, X } from 'lucide-react';
import './styles.css';

type Violation = {
  code: string;
  description: string;
  location?: string | null;
  observed_on?: string | null;
};

type CorrectiveItem = {
  code: string;
  finding: string;
  corrective_action: string;
  responsible_party: string;
  completion_target?: string | null;
  evidence?: string | null;
};

type CorrectivePlan = {
  restaurant: string;
  inspection_date: string;
  health_department: string;
  items: CorrectiveItem[];
};

type CodeCoverage = {
  code: string;
  status: 'covered' | 'incomplete';
  reasons: string[];
  is_complete: boolean;
};

type CoverageReport = {
  codes: CodeCoverage[];
  uninvited_codes: string[];
  is_complete: boolean;
  missing_codes: string[];
};

type DraftResponse = {
  plan: CorrectivePlan;
  coverage: CoverageReport;
  template_html: string;
};

type Decision = 'pending' | 'approved' | 'rejected';

type FormState = {
  restaurant: string;
  inspection_date: string;
  health_department: string;
  violations: Violation[];
};

const blankViolation = (): Violation => ({ code: '', description: '', location: '' });

const STATE_WORD: Record<Decision, string> = {
  pending: 'Awaiting',
  approved: 'Cleared',
  rejected: 'Rejected',
};

function App() {
  const [form, setForm] = React.useState<FormState>({
    restaurant: '',
    inspection_date: '',
    health_department: '',
    violations: [blankViolation()],
  });
  const [draft, setDraft] = React.useState<DraftResponse | null>(null);
  const [decisions, setDecisions] = React.useState<Record<string, Decision>>({});
  const [status, setStatus] = React.useState<'idle' | 'drafting' | 'exporting'>('idle');
  const [problem, setProblem] = React.useState('');

  const items = draft?.plan.items ?? [];
  const undecided = items.filter((item) => (decisions[item.code] ?? 'pending') === 'pending');
  const coverage = draft?.coverage ?? null;
  const canSend = draft !== null && undecided.length === 0 && coverage?.is_complete === true;

  async function loadSample() {
    setProblem('');
    try {
      const response = await fetch('/api/sample');
      if (!response.ok) throw new Error(await readProblem(response));
      setForm((await response.json()) as FormState);
      setDraft(null);
      setDecisions({});
    } catch (error) {
      setProblem(messageFrom(error, 'Could not load the sample inspection.'));
    }
  }

  async function draftPlan(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('drafting');
    setProblem('');
    try {
      const response = await fetch('/api/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error(await readProblem(response));
      const payload = (await response.json()) as DraftResponse;
      setDraft(payload);
      setDecisions(Object.fromEntries(payload.plan.items.map((item) => [item.code, 'pending'])));
    } catch (error) {
      setProblem(messageFrom(error, 'Could not draft the plan.'));
    } finally {
      setStatus('idle');
    }
  }

  async function sendToDepartment() {
    if (!draft) return;
    setStatus('exporting');
    setProblem('');
    try {
      const response = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan: draft.plan,
          violations: form.violations,
          decisions,
          format: 'html',
        }),
      });
      if (!response.ok) throw new Error(await readProblem(response));
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      const slug = form.restaurant.replace(/\W+/g, '-').toLowerCase() || 'plan';
      link.href = url;
      link.download = `corrective-plan-${slug}.html`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setProblem(messageFrom(error, 'Could not produce the document.'));
    } finally {
      setStatus('idle');
    }
  }

  function patchViolation(index: number, patch: Partial<Violation>) {
    setForm({
      ...form,
      violations: form.violations.map((v, i) => (i === index ? { ...v, ...patch } : v)),
    });
  }

  function addViolation() {
    setForm({ ...form, violations: [...form.violations, blankViolation()] });
  }

  function removeViolation(index: number) {
    setForm({ ...form, violations: form.violations.filter((_, i) => i !== index) });
  }

  function decide(code: string, decision: Decision) {
    setDecisions((current) => ({ ...current, [code]: decision }));
  }

  return (
    <>
      <header className="masthead">
        <h1>Corrective Action Plan</h1>
        <p className="sub">One response per cited code, checked before it reaches the inspector.</p>
        {form.inspection_date ? (
          <span className="deadline">Inspected {form.inspection_date}</span>
        ) : null}
      </header>

      {/* The thesis of the page: every cited code, and whether it has been answered. */}
      {coverage ? <Ledger coverage={coverage} /> : null}

      <div className="workspace">
        <aside className="intake">
          <form onSubmit={draftPlan}>
            <label className="field">
              <span>Restaurant</span>
              <input
                value={form.restaurant}
                onChange={(e) => setForm({ ...form, restaurant: e.currentTarget.value })}
              />
            </label>
            <label className="field">
              <span>Inspection date</span>
              <input
                type="date"
                value={form.inspection_date}
                onChange={(e) => setForm({ ...form, inspection_date: e.currentTarget.value })}
              />
            </label>
            <label className="field">
              <span>Health department</span>
              <input
                value={form.health_department}
                onChange={(e) => setForm({ ...form, health_department: e.currentTarget.value })}
              />
            </label>

            <div className="section-head">
              <h2>Cited violations</h2>
              <button type="button" className="btn btn--ghost" onClick={addViolation}>
                <Plus aria-hidden="true" />
                Add
              </button>
            </div>

            {form.violations.map((violation, index) => (
              <div className="cited" key={index}>
                <div className="cited__top">
                  <input
                    aria-label={`Violation ${index + 1} code`}
                    placeholder="5-202.11"
                    value={violation.code}
                    onChange={(e) => patchViolation(index, { code: e.currentTarget.value })}
                  />
                  <input
                    aria-label={`Violation ${index + 1} location`}
                    placeholder="Where"
                    value={violation.location ?? ''}
                    onChange={(e) => patchViolation(index, { location: e.currentTarget.value })}
                  />
                  {form.violations.length > 1 ? (
                    <button
                      type="button"
                      className="cited__drop"
                      aria-label={`Remove violation ${index + 1}`}
                      onClick={() => removeViolation(index)}
                    >
                      <Trash2 aria-hidden="true" size={14} />
                    </button>
                  ) : null}
                </div>
                <textarea
                  aria-label={`Violation ${index + 1} description`}
                  placeholder="What the inspector wrote"
                  value={violation.description}
                  onChange={(e) => patchViolation(index, { description: e.currentTarget.value })}
                />
              </div>
            ))}

            <div className="row" style={{ marginTop: 18 }}>
              <button type="button" className="btn btn--ghost" onClick={loadSample}>
                Use sample inspection
              </button>
              <button type="submit" className="btn" disabled={status === 'drafting'}>
                {status === 'drafting' ? <Loader2 className="spin" aria-hidden="true" /> : null}
                Draft responses
              </button>
            </div>
          </form>
        </aside>

        <section className="queue">
          <div className="queue__head">
            <div>
              <span className="eyebrow">Review</span>
              <h2>
                {items.length === 0
                  ? 'Nothing to review yet'
                  : `${items.length} response${items.length === 1 ? '' : 's'} to check`}
              </h2>
            </div>
            <button
              className="btn btn--clear"
              disabled={!canSend || status === 'exporting'}
              onClick={sendToDepartment}
            >
              {status === 'exporting' ? (
                <Loader2 className="spin" aria-hidden="true" />
              ) : (
                <Download aria-hidden="true" />
              )}
              Download for resubmission
            </button>
          </div>

          {problem ? (
            <div className="flag" role="alert">
              <h3>That did not go through</h3>
              <p>{problem}</p>
            </div>
          ) : null}

          {coverage && !coverage.is_complete ? <CoverageProblems coverage={coverage} /> : null}

          {draft && undecided.length > 0 ? (
            <div className="flag flag--note">
              <h3>{undecided.length} still awaiting your decision</h3>
              <p>Approve or reject every response before downloading. Undecided is not approved.</p>
            </div>
          ) : null}

          {items.length === 0 ? (
            <div className="empty">
              <p>Enter the violations the inspector cited, then draft responses.</p>
              <p className="eyebrow">Each code gets its own fix and its own owner</p>
            </div>
          ) : (
            <div className="cards">
              {items.map((item, index) => {
                const decision = decisions[item.code] ?? 'pending';
                const codeCoverage = coverage?.codes.find((c) => c.code === item.code);
                return (
                  <article
                    className={`card card--${decision}`}
                    key={item.code}
                    style={{ animationDelay: `${index * 55}ms` }}
                  >
                    <div className="plate">
                      <span className="plate__code">{item.code}</span>
                      <span className="plate__state">{STATE_WORD[decision]}</span>
                    </div>
                    <div className="card__body">
                      <p className="finding">{item.finding}</p>
                      <p className="action">{item.corrective_action}</p>
                      <dl className="assigned">
                        <dt>Owner</dt>
                        <dd>{item.responsible_party}</dd>
                      </dl>
                      <div className="meta">
                        <span>
                          Target <strong>{item.completion_target ?? 'not set'}</strong>
                        </span>
                        <span>
                          Evidence <strong>{item.evidence ?? 'not set'}</strong>
                        </span>
                      </div>
                      {codeCoverage && !codeCoverage.is_complete ? (
                        <div className="flag">
                          <h3>This response will not pass the coverage check</h3>
                          <ul>
                            {codeCoverage.reasons.map((reason) => (
                              <li key={reason}>{reason}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <div className="card__actions">
                        {decision !== 'pending' ? (
                          <span className="decided">{STATE_WORD[decision]}</span>
                        ) : null}
                        <button
                          className="btn btn--cite"
                          onClick={() => decide(item.code, 'rejected')}
                        >
                          <X aria-hidden="true" />
                          Reject
                        </button>
                        <button
                          className="btn btn--clear"
                          onClick={() => decide(item.code, 'approved')}
                        >
                          <Check aria-hidden="true" />
                          Approve
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </>
  );
}

/** Every cited code as a stamp, plus the verdict. The one thing worth seeing at a glance. */
function Ledger({ coverage }: { coverage: CoverageReport }) {
  return (
    <div className="ledger">
      <span className="ledger__label">Coverage</span>
      <div className="ledger__stamps">
        {coverage.codes.map((code) => (
          <span
            className={`stamp stamp--${code.is_complete ? 'covered' : 'incomplete'}`}
            key={code.code}
            title={code.reasons.join('; ') || 'Answered individually'}
          >
            {code.is_complete ? (
              <Check aria-hidden="true" size={12} />
            ) : (
              <X aria-hidden="true" size={12} />
            )}
            {code.code}
          </span>
        ))}
        {coverage.uninvited_codes.map((code) => (
          <span className="stamp stamp--uninvited" key={code} title="Not cited by the inspector">
            {code}
          </span>
        ))}
      </div>
      <span
        className={`ledger__verdict ledger__verdict--${coverage.is_complete ? 'clear' : 'blocked'}`}
      >
        {coverage.is_complete
          ? 'Every cited code answered individually'
          : 'Not every cited code is answered'}
      </span>
    </div>
  );
}

function CoverageProblems({ coverage }: { coverage: CoverageReport }) {
  const failing = coverage.codes.filter((code) => !code.is_complete);
  return (
    <div className="flag" role="status">
      <h3>
        <Stamp aria-hidden="true" size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />
        This plan cannot be sent yet
      </h3>
      {coverage.codes.length === 0 ? (
        <p>No cited violations were checked, so nothing can be declared covered.</p>
      ) : null}
      {failing.length > 0 ? (
        <ul>
          {failing.map((code) => (
            <li key={code.code}>
              <strong>{code.code}</strong> — {code.reasons.join('; ')}
            </li>
          ))}
        </ul>
      ) : null}
      {coverage.uninvited_codes.length > 0 ? (
        <p style={{ marginTop: 6 }}>
          These codes appear in the plan but were never cited:{' '}
          <strong>{coverage.uninvited_codes.join(', ')}</strong>. Remove them — a resubmission must
          answer what the inspector wrote, and nothing else.
        </p>
      ) : null}
    </div>
  );
}

async function readProblem(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === 'string') return payload.detail;
  return `${response.status} ${response.statusText}`;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
