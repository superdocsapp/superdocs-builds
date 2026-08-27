import { useEffect, useMemo, useState } from "react";
import type { CorpusSummary, Failure, Report, Summary, UnitDiff } from "./types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

const TYPE_LABELS: Record<string, string> = {
  single_sentence: "Single sentence",
  one_section: "One section",
  table_row: "Table row",
  global_rename: "Global rename",
};

const APPROACH_LABELS: Record<string, string> = {
  direct: "Direct instruction",
  search_scoped: "Search-scoped",
};

function percent(value: number) {
  return `${(value * 100).toFixed(value === 0 || value === 1 ? 0 : 1)}%`;
}

function MetricCard({ label, value, note, tone = "ink" }: { label: string; value: string; note: string; tone?: string }) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <span className="metric-note">{note}</span>
    </article>
  );
}

function ScoreBar({ value, kind }: { value: number; kind: "coverage" | "collateral" }) {
  const safeValue = Math.min(1, Math.max(0, value));
  return (
    <div className={`score-bar ${kind}`} aria-label={`${percent(value)} ${kind}`}>
      <span style={{ width: `${safeValue * 100}%` }} />
    </div>
  );
}

function BreakdownRow({ name, summary }: { name: string; summary: Summary }) {
  return (
    <div className="breakdown-row">
      <div>
        <strong>{TYPE_LABELS[name] ?? name}</strong>
        <span>{summary.cases} evaluated runs</span>
      </div>
      <div className="bar-cell">
        <span>{percent(summary.intended_change_coverage)}</span>
        <ScoreBar value={summary.intended_change_coverage} kind="coverage" />
      </div>
      <div className="bar-cell">
        <span>{percent(summary.collateral_damage_rate)}</span>
        <ScoreBar value={summary.collateral_damage_rate} kind="collateral" />
      </div>
    </div>
  );
}

function DiffCard({ diff }: { diff: UnitDiff }) {
  return (
    <article className="diff-card">
      <header>
        <code>{diff.chunk_id}</code>
        <span className={`diff-kind ${diff.classification}`}>{diff.classification.replaceAll("_", " ")}</span>
      </header>
      <div className="diff-grid">
        <div>
          <span>Before</span>
          <pre>{diff.before_html ?? "—"}</pre>
        </div>
        <div>
          <span>After</span>
          <pre>{diff.after_html ?? "—"}</pre>
        </div>
      </div>
    </article>
  );
}

function FailureExplorer({ failures }: { failures: Failure[] }) {
  const [selectedId, setSelectedId] = useState(failures[0]?.case_id ?? "");
  const selected = failures.find((item) => item.case_id === selectedId) ?? failures[0];

  useEffect(() => {
    if (failures.length && !failures.some((item) => item.case_id === selectedId)) {
      setSelectedId(failures[0].case_id);
    }
  }, [failures, selectedId]);

  if (!selected) {
    return <div className="empty-state">No precision failures were recorded in this run.</div>;
  }

  return (
    <div className="failure-layout">
      <div className="failure-list" role="list">
        {failures.map((failure) => (
          <button
            className={failure.case_id === selected.case_id ? "active" : ""}
            key={`${failure.approach}-${failure.case_id}`}
            onClick={() => setSelectedId(failure.case_id)}
            type="button"
          >
            <span>{TYPE_LABELS[failure.instruction_type] ?? failure.instruction_type}</span>
            <strong>{failure.case_id}</strong>
            <small>{APPROACH_LABELS[failure.approach] ?? failure.approach} · loss {failure.score.precision_loss.toFixed(2)}</small>
          </button>
        ))}
      </div>
      <div className="failure-detail">
        <div className="failure-summary">
          <div><span>Coverage</span><strong>{percent(selected.score.intended_change_coverage)}</strong></div>
          <div><span>Collateral</span><strong>{percent(selected.score.collateral_damage_rate)}</strong></div>
          <div><span>Precision loss</span><strong>{selected.score.precision_loss.toFixed(2)}</strong></div>
        </div>
        {selected.score.unit_diffs.map((diff) => <DiffCard diff={diff} key={diff.chunk_id} />)}
      </div>
    </div>
  );
}

export default function App() {
  const [report, setReport] = useState<Report | null>(null);
  const [corpus, setCorpus] = useState<CorpusSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/report`).then((response) => {
        if (!response.ok) throw new Error("Evaluation report is unavailable");
        return response.json();
      }),
      fetch(`${API_BASE}/api/corpus`).then((response) => {
        if (!response.ok) throw new Error("Corpus summary is unavailable");
        return response.json();
      }),
    ])
      .then(([nextReport, nextCorpus]) => {
        setReport(nextReport);
        setCorpus(nextCorpus);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const operationRatio = useMemo(
    () => report ? Math.min(1, report.actual_operations / report.operation_cap) : 0,
    [report],
  );

  if (error) {
    return <main className="center-state"><strong>Dashboard could not load</strong><p>{error}</p></main>;
  }
  if (!report || !corpus) {
    return <main className="center-state"><div className="loader" /><p>Loading evaluation evidence…</p></main>;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">EP</div>
        <div className="brand-copy">
          <strong>Edit Precision Lab</strong>
          <span>SuperDocs quality evaluation</span>
        </div>
        <div className="topbar-meta">
          <span className={`source-badge ${report.data_source}`}>{report.data_source} data</span>
          <span>Small-sample run</span>
        </div>
      </header>

      <main>
        {report.data_source === "fixture" && (
          <aside className="fixture-notice">
            <strong>Demonstration data</strong>
            <span>{report.notice}</span>
          </aside>
        )}

        <section className="hero">
          <div>
            <span className="eyebrow">Collateral damage measurement</span>
            <h1>Did the edit change only what was requested?</h1>
            <p>Coverage rewards completed target edits. Collateral rate exposes every protected chunk that changed unexpectedly.</p>
          </div>
          <div className="run-stamp">
            <span>Evaluation mode</span>
            <strong>{report.mode}</strong>
            <small>{report.overall.cases} approach × case runs</small>
          </div>
        </section>

        <section className="metrics-grid" aria-label="Evaluation summary">
          <MetricCard label="Intended coverage" value={percent(report.overall.intended_change_coverage)} note="Higher is better" tone="green" />
          <MetricCard label="Collateral damage" value={percent(report.overall.collateral_damage_rate)} note="Lower is better" tone="red" />
          <MetricCard label="Precision loss" value={report.overall.precision_loss.toFixed(2)} note="1 − coverage + collateral" tone="amber" />
          <MetricCard label="Mean latency" value={`${(report.overall.latency_ms / 1000).toFixed(1)}s`} note="End-to-end per run" tone="blue" />
        </section>

        <section className="content-grid">
          <article className="panel breakdown-panel">
            <header className="panel-header">
              <div><span className="eyebrow">Required breakdown</span><h2>By instruction type</h2></div>
              <div className="legend"><span className="coverage-dot" />Coverage <span className="collateral-dot" />Collateral</div>
            </header>
            <div className="breakdown-head"><span>Instruction</span><span>Coverage</span><span>Collateral</span></div>
            {Object.entries(report.by_instruction_type).map(([name, summary]) => (
              <BreakdownRow name={name} summary={summary} key={name} />
            ))}
          </article>

          <article className="panel budget-panel">
            <header className="panel-header"><div><span className="eyebrow">Spend guard</span><h2>Operation budget</h2></div></header>
            <div className="budget-number"><strong>{report.actual_operations}</strong><span>/ {report.operation_cap}</span></div>
            <div className="budget-track"><span style={{ width: `${operationRatio * 100}%` }} /></div>
            <div className="budget-details"><span>Declared before run</span><strong>{Math.max(0, report.operation_cap - report.actual_operations)} remaining</strong></div>
            <hr />
            <div className="corpus-stat"><span>Reusable corpus</span><strong>{corpus.cases} cases</strong></div>
            <div className="corpus-stat"><span>Ambiguous instructions</span><strong>{corpus.ambiguous_cases.length}</strong></div>
            <div className="corpus-stat"><span>Second review</span><strong className={corpus.by_review_status.pending ? "pending" : "approved"}>{corpus.by_review_status.pending ? `${corpus.by_review_status.pending} pending` : "Approved"}</strong></div>
          </article>
        </section>

        <section className="panel approaches-panel">
          <header className="panel-header"><div><span className="eyebrow">Same corpus, competing methods</span><h2>Approach comparison</h2></div></header>
          <div className="approach-grid">
            {Object.entries(report.by_approach).map(([name, summary]) => (
              <article key={name}>
                <div className="approach-title"><strong>{APPROACH_LABELS[name] ?? name}</strong><span>{summary.operations_used} ops</span></div>
                <div className="approach-metrics">
                  <div><span>Coverage</span><strong>{percent(summary.intended_change_coverage)}</strong><ScoreBar value={summary.intended_change_coverage} kind="coverage" /></div>
                  <div><span>Collateral</span><strong>{percent(summary.collateral_damage_rate)}</strong><ScoreBar value={summary.collateral_damage_rate} kind="collateral" /></div>
                  <div><span>Latency</span><strong>{(summary.latency_ms / 1000).toFixed(1)}s</strong></div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel failure-panel">
          <header className="panel-header"><div><span className="eyebrow">Evidence, not just averages</span><h2>Failure explorer</h2></div><span>{report.failures.length} cases need attention</span></header>
          <FailureExplorer failures={report.failures} />
        </section>
      </main>

      <footer>SuperDocs Edit Precision Evaluator · Chunk-level labels · Human review status preserved</footer>
    </div>
  );
}
