import * as React from 'react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, Download, FileWarning, Loader2, Scale, X } from 'lucide-react';
import './styles.css';

type Doc = { name: string; text: string };
type Event = { kind: string; on: string; by: string; note?: string | null };

type Section = {
  id: string;
  area: string;
  heading: string;
  verdict: 'conflict' | 'silence' | 'agree';
  buyer_says: string[];
  supplier_says: string[];
  silent_party: 'buyer' | 'supplier' | null;
  comment: string;
};

type Governing = {
  doctrine: string;
  rule_id: string | null;
  likely_to_govern: 'buyer' | 'supplier' | null;
  conclusion: string;
  reasoning: string;
  prose: string;
  is_inconclusive: boolean;
  missing_to_decide: string[];
};

type Memo = {
  buyer_document: string;
  supplier_document: string;
  summary: string;
  conflicts: Section[];
  silences: Section[];
  agreements: Section[];
  unaddressed: string[];
  governing: Governing | null;
};

type Instruction = { document: string; phrase: string; quote: string };
type Comparison = { memo: Memo; instruction_findings: Instruction[] };
type Decision = 'pending' | 'approved' | 'rejected';

const EVENT_WORDS: Record<string, string> = {
  po_issued: 'Purchase order issued',
  acknowledgement_returned: 'Acknowledgement returned',
  objection_sent: 'Objection sent',
  goods_delivered: 'Goods delivered',
  goods_accepted: 'Goods accepted',
  invoice_paid: 'Invoice paid',
};

const TERMS_EVENTS = new Set(['po_issued', 'acknowledgement_returned']);
const PERFORMANCE_EVENTS = new Set(['goods_delivered', 'goods_accepted', 'invoice_paid']);

function App() {
  const [pile, setPile] = React.useState('pile-a');
  const [buyer, setBuyer] = React.useState<Doc | null>(null);
  const [supplier, setSupplier] = React.useState<Doc | null>(null);
  const [sequence, setSequence] = React.useState<Event[]>([]);
  const [orderRef, setOrderRef] = React.useState('');
  const [result, setResult] = React.useState<Comparison | null>(null);
  const [decisions, setDecisions] = React.useState<Record<string, Decision>>({});
  const [busy, setBusy] = React.useState<'idle' | 'comparing' | 'exporting'>('idle');
  const [problem, setProblem] = React.useState('');

  const memo = result?.memo ?? null;
  const outstanding = memo ? [...memo.conflicts, ...memo.silences] : [];
  const undecided = outstanding.filter((s) => (decisions[s.id] ?? 'pending') === 'pending');
  const raised = outstanding.filter((s) => decisions[s.id] === 'approved');

  async function load(which: string) {
    setProblem('');
    try {
      const response = await fetch(`/api/sample?pile=${which}`);
      if (!response.ok) throw new Error(await detail(response));
      const payload = await response.json();
      setBuyer(payload.buyer);
      setSupplier(payload.supplier);
      setSequence(payload.sequence);
      setOrderRef(payload.order_reference);
      setResult(null);
      setDecisions({});
    } catch (error) {
      setProblem(message(error, 'Could not load that pile.'));
    }
  }

  async function compare() {
    if (!buyer || !supplier) return;
    setBusy('comparing');
    setProblem('');
    try {
      const response = await fetch('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ buyer, supplier, sequence }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const payload = (await response.json()) as Comparison;
      setResult(payload);
      setDecisions(
        Object.fromEntries(
          [...payload.memo.conflicts, ...payload.memo.silences].map((s) => [s.id, 'pending']),
        ),
      );
    } catch (error) {
      setProblem(message(error, 'Could not compare the documents.'));
    } finally {
      setBusy('idle');
    }
  }

  async function download(document_: 'memo' | 'letter') {
    if (!buyer || !supplier) return;
    setBusy('exporting');
    setProblem('');
    try {
      const response = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          buyer,
          supplier,
          sequence,
          decisions,
          document: document_,
          format: 'html',
          to: supplier.name,
          from_: buyer.name,
          order_reference: orderRef,
        }),
      });
      if (!response.ok) throw new Error(await detail(response));
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement('a');
      link.href = url;
      link.download = `${document_}-${orderRef || 'order'}.html`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setProblem(message(error, 'Could not produce the document.'));
    } finally {
      setBusy('idle');
    }
  }

  return (
    <>
      <header className="masthead">
        <h1>Terms Conflict Checker</h1>
        <p className="sub">Both sides quoted on every contested point. Silence reported as silence.</p>
        {buyer && supplier ? (
          <span className="docs-pair">
            {buyer.name} <span className="vs">vs</span> {supplier.name}
          </span>
        ) : null}
      </header>

      {memo ? (
        <div className="tally">
          <span className="count count--contested">
            <b>{memo.conflicts.length}</b> contested
          </span>
          <span className="count count--silent">
            <b>{memo.silences.length}</b> one side silent
          </span>
          <span className="count count--agreed">
            <b>{memo.agreements.length}</b> agreed
          </span>
          {memo.unaddressed.length > 0 ? (
            <span className="count">
              <b>{memo.unaddressed.length}</b> addressed by neither
            </span>
          ) : null}
          <span className="spacer" />
          <button
            className="btn btn--ghost"
            onClick={() => download('memo')}
            disabled={busy !== 'idle'}
          >
            <Download aria-hidden="true" />
            Memo
          </button>
          <button
            className="btn"
            onClick={() => download('letter')}
            disabled={busy !== 'idle' || undecided.length > 0}
            title={
              undecided.length > 0
                ? `${undecided.length} finding(s) still undecided`
                : 'Produce the letter'
            }
          >
            {busy === 'exporting' ? (
              <Loader2 className="spin" aria-hidden="true" />
            ) : (
              <Download aria-hidden="true" />
            )}
            Letter ({raised.length} raised)
          </button>
        </div>
      ) : null}

      <div className="workspace">
        <aside className="controls">
          <label className="field">
            <span>Sample pile</span>
            <select
              value={pile}
              onChange={(e) => {
                setPile(e.currentTarget.value);
                load(e.currentTarget.value);
              }}
            >
              <option value="pile-a">pile-a — machined housings, terms disputed</option>
              <option value="pile-b">pile-b — subsea survey, largely agreed</option>
            </select>
          </label>

          <div className="row">
            <button className="btn btn--ghost" onClick={() => load(pile)}>
              Load documents
            </button>
            <button className="btn" onClick={compare} disabled={!buyer || busy === 'comparing'}>
              {busy === 'comparing' ? <Loader2 className="spin" aria-hidden="true" /> : null}
              Compare
            </button>
          </div>

          {sequence.length > 0 ? (
            <>
              <h2 className="block-head">Sequence of events</h2>
              <p className="caveat" style={{ marginTop: 0, marginBottom: 10 }}>
                Order and dates decide which document governs.
              </p>
              <ol className="timeline">
                {sequence.map((event, index) => (
                  <li
                    className={`moment moment--${
                      TERMS_EVENTS.has(event.kind)
                        ? 'terms'
                        : PERFORMANCE_EVENTS.has(event.kind)
                          ? 'performance'
                          : 'objection'
                    }`}
                    key={index}
                  >
                    <time>{event.on}</time>
                    <div>
                      <div className="what">{EVENT_WORDS[event.kind] ?? event.kind}</div>
                      <div className="who">{event.by}</div>
                    </div>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </aside>

        <section className="findings">
          {problem ? (
            <div className="notice notice--alarm" role="alert">
              <h3>That did not go through</h3>
              <p>{problem}</p>
            </div>
          ) : null}

          {result?.instruction_findings?.length ? (
            <div className="notice notice--alarm">
              <h3>
                <FileWarning aria-hidden="true" size={13} style={{ verticalAlign: '-2px' }} /> A
                document tried to give instructions
              </h3>
              <p>
                The text below was found inside a source document and appears to address this tool.
                It was <strong>reported, not acted on</strong>, and the findings below stand.
              </p>
              {result.instruction_findings.map((finding, index) => (
                <blockquote key={index}>
                  {finding.document}: “{finding.quote}”
                </blockquote>
              ))}
            </div>
          ) : null}

          {memo?.governing ? <Governs governing={memo.governing} /> : null}

          {!memo ? (
            <div className="empty">
              <p>Load a pile and compare the two documents.</p>
            </div>
          ) : null}

          {memo && undecided.length > 0 ? (
            <div className="notice">
              <h3>{undecided.length} finding(s) still undecided</h3>
              <p>
                Decide each one before producing the letter. Raising a point puts it in the letter;
                dropping it leaves it in the memo but out of the letter.
              </p>
            </div>
          ) : null}

          {memo && memo.conflicts.length > 0 ? (
            <>
              <div className="section-label">Contested points</div>
              {memo.conflicts.map((section) => (
                <Dispute
                  key={section.id}
                  section={section}
                  decision={decisions[section.id] ?? 'pending'}
                  onDecide={(d) => setDecisions((c) => ({ ...c, [section.id]: d }))}
                />
              ))}
            </>
          ) : null}

          {/* Deliberately its own band. A silence listed among conflicts reads as an agreement. */}
          {memo && memo.silences.length > 0 ? (
            <>
              <div className="section-label">One document is silent — nothing agreed here</div>
              {memo.silences.map((section) => (
                <Dispute
                  key={section.id}
                  section={section}
                  decision={decisions[section.id] ?? 'pending'}
                  onDecide={(d) => setDecisions((c) => ({ ...c, [section.id]: d }))}
                />
              ))}
            </>
          ) : null}

          {memo && memo.agreements.length > 0 ? (
            <>
              <div className="section-label">Agreed</div>
              {memo.agreements.map((section) => (
                <Dispute key={section.id} section={section} decision="pending" readOnly />
              ))}
            </>
          ) : null}

          {memo && memo.unaddressed.length > 0 ? (
            <div className="notice">
              <h3>Addressed by neither document</h3>
              <p>
                {memo.unaddressed.join(', ')} — gaps in the paperwork rather than disagreements
                within it.
              </p>
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}

/** Two documents, facing. The gutter between them is the dispute. */
function Dispute({
  section,
  decision,
  onDecide,
  readOnly = false,
}: {
  section: Section;
  decision: Decision;
  onDecide?: (decision: Decision) => void;
  readOnly?: boolean;
}) {
  const decided = decision !== 'pending';
  return (
    <article
      className={`dispute dispute--${section.verdict === 'silence' ? 'silence' : 'contested'} ${
        decided ? 'dispute--decided' : ''
      }`}
    >
      <div className="dispute__head">
        <h3>{section.heading}</h3>
        <span className={`verdict-tag verdict-tag--${section.verdict}`}>{section.verdict}</span>
        {decided ? (
          <span className="state-tag">{decision === 'approved' ? 'Raised' : 'Dropped'}</span>
        ) : null}
      </div>

      <p className="comment">{section.comment}</p>

      <div className="pages">
        <Page title="The buyer's document" quotes={section.buyer_says} party="buyer" />
        <div className="gutter" />
        <Page title="The supplier's document" quotes={section.supplier_says} party="supplier" />
      </div>

      {!readOnly && onDecide ? (
        <div className="dispute__actions">
          <button className="btn btn--drop" onClick={() => onDecide('rejected')}>
            <X aria-hidden="true" />
            Do not raise
          </button>
          <button className="btn btn--raise" onClick={() => onDecide('approved')}>
            <Check aria-hidden="true" />
            Raise in the letter
          </button>
        </div>
      ) : null}
    </article>
  );
}

function Page({
  title,
  quotes,
  party,
}: {
  title: string;
  quotes: string[];
  party: 'buyer' | 'supplier';
}) {
  if (quotes.length === 0) {
    return (
      <div className="page page--empty">
        <h4>{title}</h4>
        <p className="void">
          <strong>No provision.</strong>
          This document does not address the point. Nothing has been agreed on it — the {party} has
          simply not answered.
        </p>
      </div>
    );
  }
  return (
    <div className="page">
      <h4>{title}</h4>
      {quotes.map((quote, index) => (
        <blockquote key={index}>{quote}</blockquote>
      ))}
    </div>
  );
}

function Governs({ governing }: { governing: Governing }) {
  return (
    <section className="governs">
      <h2>
        <Scale aria-hidden="true" size={12} style={{ verticalAlign: '-1px', marginRight: 5 }} />
        Which document is likely to govern
      </h2>
      <p className="call">{governing.conclusion}</p>
      <div className="rule">
        {governing.doctrine}
        {governing.rule_id ? ` · rule ${governing.rule_id}` : ''}
      </div>

      {governing.missing_to_decide.length > 0 ? (
        <ul>
          {governing.missing_to_decide.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}

      <details>
        <summary>What this conclusion rests on</summary>
        <pre>{governing.prose}</pre>
      </details>

      <p className="caveat">
        A triage position from the recorded sequence and a stated doctrine — not legal advice.
        Confirm with counsel before relying on it.
      </p>
    </section>
  );
}

async function detail(response: Response): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (payload && typeof payload.detail === 'string') return payload.detail;
  return `${response.status} ${response.statusText}`;
}

function message(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
