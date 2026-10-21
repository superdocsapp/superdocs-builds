import { Link } from "react-router-dom";
import { useEvidence } from "../evidence";
import { api, ApiError } from "../api";
import { useCorpus } from "../corpus";
import type { ArchitectureSummary, SuperDocsStatus } from "../types";
import { Disclosure } from "../components/Disclosure";
import { InfoBanner } from "../components/InfoBanner";
import { MetricsRow } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { ErrorBanner, Loading } from "../components/Status";
import { useEffect, useState } from "react";

const PRINCIPLES = [
  "Evidence-first",
  "Honest uncertainty",
  "Human at the gate",
  "Surgical propagation",
  "Deterministic offline core",
];

export function OverviewPage() {
  const { corpusId, analyzed, analyze, loading } = useCorpus();
  const { openEvidence } = useEvidence();
  const [summary, setSummary] = useState<ArchitectureSummary | null>(null);
  const [status, setStatus] = useState<SuperDocsStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError(null);
      try {
        const superdocs = await api.superdocs();
        if (!cancelled) setStatus(superdocs);
        if (analyzed && corpusId) {
          const architecture = await api.architecture(corpusId);
          if (!cancelled) setSummary(architecture);
        } else if (!cancelled) {
          setSummary(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load overview.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [corpusId, analyzed]);

  if (loading && !summary) return <Loading label="Loading workspace" />;
  if (error) return <ErrorBanner message={error} />;

  const metrics = summary?.metrics;
  const nextAction = nextUsefulAction(analyzed, metrics);

  return (
    <section>
      <PageHeader kicker={summary?.organization ?? "Workspace"} title="Overview">
        Families, tracks, levels, and surgical updates from this corpus. Titles never determine level.
      </PageHeader>
      <p className="workflow-trail">
        Sources → Architecture → Exceptions → Framework → Profiles → Change impact → Human review → Export
      </p>
      {!analyzed ? (
        <div className="empty">
          This corpus has not been analyzed yet.
          <div className="actions" style={{ marginTop: "0.75rem" }}>
            <button type="button" className="primary" onClick={() => void analyze()}>
              Analyze
            </button>
          </div>
        </div>
      ) : metrics ? (
        <>
          <MetricsRow metrics={metrics} />
          <InfoBanner>
            {healthCopy(metrics)} {nextAction}
          </InfoBanner>
        </>
      ) : null}
      <div className="grid-2">
        <article className="card reviewer-path">
          <h2>Reviewer path</h2>
          <ol className="reviewer-steps">
            <li>
              <span className="step-marker">
                <span className="step-index" aria-hidden="true">
                  1
                </span>
              </span>
              <div className="step-copy">
                <strong>
                  <Link to="/architecture">Inspect clusters</Link>
                </strong>
                <p>Understand natural groupings from evidence neighborhoods.</p>
              </div>
            </li>
            <li>
              <span className="step-marker">
                <span className="step-index" aria-hidden="true">
                  2
                </span>
              </span>
              <div className="step-copy">
                <strong>
                  <Link to="/exceptions">Provisional and misfit</Link>
                </strong>
                <p>Review uncertain or out-of-architecture roles. Nothing is auto-assigned.</p>
              </div>
            </li>
            <li>
              <span className="step-marker">
                <span className="step-index" aria-hidden="true">
                  3
                </span>
              </span>
              <div className="step-copy">
                <strong>
                  <Link to="/impact">Canonical level edit</Link>
                </strong>
                <p>Propose a surgical change, then send it to human review.</p>
              </div>
            </li>
          </ol>
        </article>
        <article className="card">
          <div className="superdocs-head">
            <h2>SuperDocs</h2>
            <span className={`chip ${status?.configured ? "good" : "warn"}`}>
              {status?.configured ? "configured" : "not configured"}
            </span>
          </div>
          {status?.configured ? (
            <p>Configured on this server. Architecture review still works in this app.</p>
          ) : (
            <p>Not configured. Architecture review works fully offline.</p>
          )}
          {status?.live_export_reason ? (
            <Disclosure title="Live export details">
              <p>{status.live_export_reason}</p>
            </Disclosure>
          ) : null}
          <p className="helper evidence-cta">
            Live verification evidence available.
            <button type="button" className="text-btn" onClick={openEvidence}>
              View evidence
            </button>
          </p>
        </article>
      </div>
      <ul className="principle-strip">
        {PRINCIPLES.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function healthCopy(metrics: ArchitectureSummary["metrics"]): string {
  const occupied = metrics.strong_fits + metrics.provisional;
  return `${metrics.proposed_families} families and ${metrics.tracks} tracks cover ${occupied} classified roles. ${metrics.misfits} misfit ${metrics.misfits === 1 ? "role sits" : "roles sit"} outside the architecture.`;
}

function nextUsefulAction(
  analyzed: boolean,
  metrics: ArchitectureSummary["metrics"] | undefined,
) {
  if (!analyzed || !metrics) return null;
  if (metrics.misfits > 0 || metrics.provisional > 0) {
    return (
      <>
        Next: review <Link to="/exceptions">exceptions</Link>.
      </>
    );
  }
  return (
    <>
      Next: inspect <Link to="/architecture">clusters</Link> or a{" "}
      <Link to="/impact">canonical level change</Link>.
    </>
  );
}
