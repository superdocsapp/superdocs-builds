import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Disclosure } from "../components/Disclosure";
import { RoleDrawer } from "../components/RoleDrawer";
import { MetricsRow } from "../components/Metric";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBanner, FitChip, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import type { ArchitectureSummary, RoleDetail } from "../types";

export function ArchitecturePage() {
  const { corpusId, analyzed } = useCorpus();
  const [summary, setSummary] = useState<ArchitectureSummary | null>(null);
  const [role, setRole] = useState<RoleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analyzed) {
      setSummary(null);
      return;
    }
    let cancelled = false;
    api
      .architecture(corpusId)
      .then((payload) => {
        if (!cancelled) setSummary(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load architecture.");
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, analyzed]);

  async function openRole(roleId: string) {
    try {
      setRole(await api.role(corpusId, roleId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load role.");
    }
  }

  if (!analyzed) return <Empty>Analyze the corpus to see proposed families and clusters.</Empty>;
  if (error) return <ErrorBanner message={error} />;
  if (!summary) return <Loading label="Loading architecture" />;

  return (
    <section>
      <PageHeader kicker={summary.organization} title="Architecture">
        Clusters are evidence neighborhoods. Title wording is shown only when it conflicts with the
        evidence-based track or level.
      </PageHeader>
      <MetricsRow metrics={summary.metrics} />
      {summary.title_conflicts.length > 0 ? (
        <div className="title-vs-evidence">
          <h2>Title vs evidence</h2>
          <p className="lede">
            Titles did not classify these roles. The signals below compare the title wording to the
            evidence-based track and level.
          </p>
          <div className="grid-2">
            {summary.title_conflicts.map((item) => (
              <article className="card conflict-card" key={item.role_id}>
                <div className="cluster-head">
                  <h3>{item.title}</h3>
                  <FitChip status={item.fit_status} />
                </div>
                <dl className="def-list">
                  <div>
                    <dt>Title signal</dt>
                    <dd>{item.title_conflict.title_signal}.</dd>
                  </div>
                  <div>
                    <dt>Evidence-based outcome</dt>
                    <dd>{item.title_conflict.evidence_result}.</dd>
                  </div>
                  <div>
                    <dt>Why it differs</dt>
                    <dd>{item.title_conflict.summary}</dd>
                  </div>
                </dl>
                <div className="actions">
                  <button type="button" className="ghost" onClick={() => void openRole(item.role_id)}>
                    Open evidence
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
      <h2>Craft neighborhoods</h2>
      <div className="stack">
      {summary.clusters.map((cluster) => (
        <article className="card" key={cluster.cluster_id}>
          <div className="cluster-head">
            <h3>{cluster.proposed_family ?? "Unlabeled cluster"}</h3>
            <span className="chip">{cluster.members.length} roles</span>
            <span className="chip">cohesion {cluster.cohesion.toFixed(2)}</span>
            {cluster.separation != null ? (
              <span className="chip">separation {cluster.separation.toFixed(2)}</span>
            ) : null}
          </div>
          <Disclosure title="Cluster members and nearest neighbor">
            {cluster.nearest_cluster_id ? (
              <p>
                Nearest cluster {cluster.nearest_cluster_id}
                {cluster.nearest_cluster_similarity != null
                  ? ` (${cluster.nearest_cluster_similarity.toFixed(2)})`
                  : ""}
              </p>
            ) : null}
            <ul className="member-list">
              {cluster.members.map((member) => (
                <li key={member.role_id}>
                  <button type="button" className="row-btn" onClick={() => void openRole(member.role_id)}>
                    {member.title}
                    {member.is_ambiguous ? " (ambiguous)" : ""}
                  </button>
                </li>
              ))}
            </ul>
          </Disclosure>
        </article>
      ))}
      </div>
      {role ? <RoleDrawer role={role} onClose={() => setRole(null)} /> : null}
    </section>
  );
}
