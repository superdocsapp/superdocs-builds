import * as React from 'react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, Download, FileText, Loader2, RotateCcw, X } from 'lucide-react';
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

type CoverageReport = {
  is_complete: boolean;
  missing_codes: string[];
  uninvited_codes: string[];
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

const blankViolation = (): Violation => ({
  code: '',
  description: '',
  location: '',
});

function App() {
  const [form, setForm] = React.useState<FormState>({
    restaurant: '',
    inspection_date: '',
    health_department: '',
    violations: [blankViolation(), blankViolation(), blankViolation()],
  });
  const [draft, setDraft] = React.useState<DraftResponse | null>(null);
  const [decisions, setDecisions] = React.useState<Record<string, Decision>>({});
  const [status, setStatus] = React.useState<'idle' | 'loading' | 'exporting'>('idle');
  const [message, setMessage] = React.useState<string>('');

  const allDecided =
    draft !== null &&
    draft.plan.items.every((item) => decisions[item.code] !== undefined && decisions[item.code] !== 'pending');

  async function loadSample() {
    setStatus('loading');
    setMessage('');
    try {
      const response = await fetch('/api/sample');
      if (!response.ok) throw new Error(await errorText(response));
      const payload = (await response.json()) as FormState;
      setForm(payload);
      setDraft(null);
      setDecisions({});
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'sample load failed');
    } finally {
      setStatus('idle');
    }
  }

  async function draftPlan(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('loading');
    setMessage('');
    try {
      const response = await fetch('/api/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const payload = (await response.json()) as DraftResponse;
      setDraft(payload);
      setDecisions(Object.fromEntries(payload.plan.items.map((item) => [item.code, 'pending'])));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'draft failed');
    } finally {
      setStatus('idle');
    }
  }

  async function exportPlan(format: 'html') {
    if (!draft) return;
    setStatus('exporting');
    setMessage('');
    try {
      const response = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan: draft.plan,
          violations: form.violations,
          decisions,
          format,
        }),
      });
      if (!response.ok) throw new Error(await errorText(response));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `corrective-plan.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'export failed');
    } finally {
      setStatus('idle');
    }
  }

  function updateViolation(index: number, patch: Partial<Violation>) {
    setForm({
      ...form,
      violations: form.violations.map((violation, current) => (current === index ? { ...violation, ...patch } : violation)),
    });
  }

  return (
    <main className="shell">
      <section className="workspace">
        <aside className="panel input-panel">
          <div className="panel-title">
            <FileText aria-hidden="true" />
            <h1>Corrective plan</h1>
          </div>
          <form onSubmit={draftPlan} className="form-stack">
            <label>
              Restaurant
              <input value={form.restaurant} onChange={(event) => setForm({ ...form, restaurant: event.currentTarget.value })} />
            </label>
            <label>
              Inspection date
              <input
                type="date"
                value={form.inspection_date}
                onChange={(event) => setForm({ ...form, inspection_date: event.currentTarget.value })}
              />
            </label>
            <label>
              Health department
              <input
                value={form.health_department}
                onChange={(event) => setForm({ ...form, health_department: event.currentTarget.value })}
              />
            </label>
            <div className="violation-editor">
              {form.violations.map((violation, index) => (
                <div className="violation-row" key={index}>
                  <input
                    aria-label={`Violation ${index + 1} code`}
                    placeholder="Code"
                    value={violation.code}
                    onChange={(event) => updateViolation(index, { code: event.currentTarget.value })}
                  />
                  <input
                    aria-label={`Violation ${index + 1} location`}
                    placeholder="Location"
                    value={violation.location ?? ''}
                    onChange={(event) => updateViolation(index, { location: event.currentTarget.value })}
                  />
                  <textarea
                    aria-label={`Violation ${index + 1} description`}
                    placeholder="Description"
                    value={violation.description}
                    onChange={(event) => updateViolation(index, { description: event.currentTarget.value })}
                  />
                </div>
              ))}
            </div>
            <div className="button-row">
              <button type="button" className="secondary" onClick={loadSample}>
                <RotateCcw aria-hidden="true" />
                Sample
              </button>
              <button type="submit" disabled={status === 'loading'}>
                {status === 'loading' ? <Loader2 className="spin" aria-hidden="true" /> : <FileText aria-hidden="true" />}
                Draft
              </button>
            </div>
          </form>
        </aside>

        <section className="review-surface">
          <div className="toolbar">
            <div>
              <span className="eyebrow">Review queue</span>
              <h2>{draft ? `${draft.plan.items.length} cited items` : 'No draft loaded'}</h2>
            </div>
            <div className="button-row compact">
              <button className="secondary" disabled={!allDecided || status === 'exporting'} onClick={() => exportPlan('html')}>
                <Download aria-hidden="true" />
                HTML
              </button>
            </div>
          </div>
          {message ? <p className="notice">{message}</p> : null}
          <div className="cards">
            {draft?.plan.items.map((item) => (
              <article className={`review-card ${decisions[item.code]}`} key={item.code}>
                <header>
                  <span className="code">{item.code}</span>
                  <span className="owner">{item.responsible_party}</span>
                </header>
                <p className="finding">{item.finding}</p>
                <div className="action-block">{item.corrective_action}</div>
                <dl>
                  <div>
                    <dt>Target</dt>
                    <dd>{item.completion_target ?? 'Not set'}</dd>
                  </div>
                  <div>
                    <dt>Evidence</dt>
                    <dd>{item.evidence ?? 'Not set'}</dd>
                  </div>
                </dl>
                <footer>
                  <button className="secondary" onClick={() => setDecisions({ ...decisions, [item.code]: 'rejected' })}>
                    <X aria-hidden="true" />
                    Reject
                  </button>
                  <button onClick={() => setDecisions({ ...decisions, [item.code]: 'approved' })}>
                    <Check aria-hidden="true" />
                    Approve
                  </button>
                </footer>
              </article>
            )) ?? <div className="empty-state">Load the sample or enter cited violations.</div>}
          </div>
        </section>
      </section>
    </main>
  );
}

async function errorText(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === 'string') return payload.detail;
  return `${response.status} ${response.statusText}`;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
