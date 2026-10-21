import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Disclosure } from "../components/Disclosure";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBanner, FitChip, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import type { ExceptionCard } from "../types";

export function ExceptionsPage() {
  const { corpusId, analyzed } = useCorpus();
  const [rows, setRows] = useState<{
    provisional: ExceptionCard[];
    hybrid_bridge: ExceptionCard[];
    misfit: ExceptionCard[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!analyzed) {
      setRows(null);
      return;
    }
    let cancelled = false;
    api
      .exceptions(corpusId)
      .then((payload) => {
        if (!cancelled) setRows(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Unable to load exceptions.");
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, analyzed]);

  if (!analyzed) return <Empty>Analyze the corpus to review provisional and misfit roles.</Empty>;
  if (error) return <ErrorBanner message={error} />;
  if (!rows) return <Loading label="Loading exceptions" />;

  return (
    <section>
      <PageHeader title="Provisional and misfit review">
        Misfits are valid architecture findings, not errors to auto-assign. They require an
        architecture decision.
      </PageHeader>
      <Bucket
        title="Provisional"
        note="Evidence is incomplete or in tension. The role stays marked until a reviewer decides."
        items={rows.provisional}
      />
      <Bucket
        title="Hybrid / bridge"
        note="Evidence spans more than one craft. The role is left as a bridge, not forced into one family."
        items={rows.hybrid_bridge}
      />
      <Bucket
        title="Misfit"
        note="Work sits outside the supported architecture. This is an intentional finding, not an application error."
        items={rows.misfit}
      />
    </section>
  );
}

function Bucket({
  title,
  note,
  items,
}: {
  title: string;
  note: string;
  items: ExceptionCard[];
}) {
  return (
    <section className="exception-bucket">
      <h2>
        {title}
        <span className="chip neutral">{items.length}</span>
      </h2>
      <p className="exception-note">{note}</p>
      {items.length === 0 ? (
        <Empty>None in this bucket.</Empty>
      ) : (
        <div className="grid-2">
          {items.map((item) => (
            <article className={`card exception-card ${item.bucket || item.fit_status}`} key={item.role_id}>
              <h3>{item.title}</h3>
              <div className="actions">
                <FitChip status={item.fit_status} />
                <span className="chip">{item.status.replace(/_/g, " ")}</span>
              </div>
              {item.why ? <p className="reason-line">{item.why}</p> : null}
              {item.nearest_cluster_id || !item.has_normalized_profile ? (
                <Disclosure title="Evidence detail">
                  {item.nearest_cluster_id ? (
                    <p>
                      Nearest architecture context: cluster {item.nearest_cluster_id}
                      {item.nearest_similarity != null ? ` (${item.nearest_similarity.toFixed(2)})` : ""}.
                    </p>
                  ) : null}
                  {item.has_normalized_profile ? null : (
                    <p>Shown as a review artifact, not a normalized profile.</p>
                  )}
                </Disclosure>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
