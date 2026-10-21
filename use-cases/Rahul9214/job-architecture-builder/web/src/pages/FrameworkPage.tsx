import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Disclosure } from "../components/Disclosure";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBanner, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import type { FrameworkPayload } from "../types";

export function FrameworkPage() {
  const { corpusId, analyzed } = useCorpus();
  const [framework, setFramework] = useState<FrameworkPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analyzed) {
      setFramework(null);
      return;
    }
    let cancelled = false;
    api
      .framework(corpusId)
      .then((payload) => {
        if (!cancelled) setFramework(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load framework.");
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, analyzed]);

  if (!analyzed) return <Empty>Analyze the corpus to render the canonical framework.</Empty>;
  if (error) return <ErrorBanner message={error} />;
  if (!framework) return <Loading label="Loading framework" />;

  const ic = framework.levels.filter((item) => item.label.startsWith("IC"));
  const managers = framework.levels.filter((item) => item.label.startsWith("M"));

  return (
    <section>
      <PageHeader kicker={framework.organization} title="Framework">
        {framework.purpose}
      </PageHeader>
      <Disclosure title={`Principles (${framework.principles.length})`}>
        <ul>
          {framework.principles.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Disclosure>
      <div className="track-grid">
        {framework.tracks.map((track) => (
          <div className="track-item" key={track.id}>
            <h2>{track.name}</h2>
            <p>{track.description}</p>
          </div>
        ))}
      </div>
      <LevelTable title="Individual contributor levels" rows={ic} />
      <LevelTable title="People manager levels" rows={managers} />
      <h2>Job families</h2>
      <div className="track-grid">
        {framework.families.map((family) => (
          <div className="track-item" key={family.id}>
            <h3>{family.name}</h3>
            <p>{family.description}</p>
          </div>
        ))}
      </div>
      <h2>Provisional and misfit summary</h2>
      <div className="grid-2">
        <article className="card">
          <h3>Provisional</h3>
          {framework.provisional_summary.length ? (
            <ul>
              {framework.provisional_summary.map((item) => (
                <li key={item.role_id}>
                  {item.title}: {item.summary}
                </li>
              ))}
            </ul>
          ) : (
            <p>None.</p>
          )}
        </article>
        <article className="card">
          <h3>Misfit</h3>
          {framework.misfit_summary.length ? (
            <ul>
              {framework.misfit_summary.map((item) => (
                <li key={item.role_id}>
                  {item.title}: {item.summary}
                </li>
              ))}
            </ul>
          ) : (
            <p>None.</p>
          )}
        </article>
      </div>
      <h2>Competency matrices</h2>
      {framework.competency_matrices.map((matrix) => (
        <Disclosure key={matrix.family_id} title={matrix.family_name} defaultOpen={false}>
          {matrix.evidence_limited ? <p>{matrix.limitation}</p> : null}
          <ul>
            {matrix.competencies.map((item) => (
              <li key={item.id}>
                <strong>{item.name}.</strong> {item.description}
              </li>
            ))}
          </ul>
        </Disclosure>
      ))}
    </section>
  );
}

function LevelTable({
  title,
  rows,
}: {
  title: string;
  rows: FrameworkPayload["levels"];
}) {
  return (
    <section>
      <h2>{title}</h2>
      <div className="table-wrap">
        <table className="level-table">
          <thead>
            <tr>
              <th>Level</th>
              <th>Scope</th>
              <th>Autonomy / decision authority</th>
              <th>Complexity</th>
              <th>Impact</th>
              <th>Leadership</th>
              <th>People management</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.label} v{row.version}
                </td>
                <td>{row.scope}</td>
                <td>{row.autonomy_decision}</td>
                <td>{row.complexity}</td>
                <td>{row.impact}</td>
                <td>{row.leadership}</td>
                <td>{row.people_management || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
