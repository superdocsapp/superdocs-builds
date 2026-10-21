import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { BeforeAfter } from "../components/BeforeAfter";
import { PageHeader } from "../components/PageHeader";
import { ReviewState } from "../components/ReviewState";
import { Empty, ErrorBanner, Loading } from "../components/Status";
import { useCorpus } from "../corpus";
import type { ReviewPayload } from "../types";

export function ReviewPage() {
  const { corpusId, analyzed } = useCorpus();
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setReview(await api.review(corpusId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load review.");
    }
  }

  useEffect(() => {
    setReview(null);
    setError(null);
    if (!analyzed) return;
    void load();
    // corpus-scoped reload only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzed, corpusId]);

  async function decide(planId: string, approved: boolean) {
    setBusy(true);
    setError(null);
    try {
      setReview(await api.decisions(corpusId, [{ plan_id: planId, approved }]));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to record decision.");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      setReview(await api.apply(corpusId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Apply failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!analyzed) return <Empty>Analyze the corpus, then plan a level change to open review.</Empty>;
  if (error && !review) return <ErrorBanner message={error} />;
  if (!review) return <Loading label="Loading review" />;
  if (review.empty) return <Empty>{review.message ?? "No pending review."}</Empty>;

  const decided = review.plans.every((item) => item.decision === true || item.decision === false);

  return (
    <section>
      <PageHeader title="Human review">
        Each proposal needs an explicit approve or reject. Rejected updates remain unapplied. Apply is a
        separate step after decisions are recorded.
      </PageHeader>
      {error ? <ErrorBanner message={error} /> : null}
      <ReviewState
        remoteOperation={review.remote_operation}
        reviewOutcome={review.review_outcome}
        mutationApplied={review.mutation_applied}
        domainApplied={review.domain_applied}
      />
      <div className="stack">
        {review.plans.map((plan) => (
          <article className="card" key={plan.plan_id}>
            <h2>
              {plan.profile_id} · {plan.section_id}
            </h2>
            <p>{plan.reason}</p>
            <p>
              Dependency {plan.dependency.id} · source v{plan.dependency.source_version}
            </p>
            <BeforeAfter before={plan.before} after={plan.after} />
            <p>
              Decision:{" "}
              {plan.decision === true ? "approved" : plan.decision === false ? "rejected" : "undecided"}
            </p>
            <div className="actions">
              <button
                type="button"
                className="primary"
                disabled={busy || review.domain_applied}
                onClick={() => void decide(plan.plan_id, true)}
              >
                Approve
              </button>
              <button
                type="button"
                className="danger"
                disabled={busy || review.domain_applied}
                onClick={() => void decide(plan.plan_id, false)}
              >
                Reject
              </button>
            </div>
          </article>
        ))}
      </div>
      {review.preservation ? (
        <article className="card" style={{ marginTop: "1rem" }}>
          <h2>Unrelated sections preserved</h2>
          <p>
            {review.preservation.unrelated_sections_preserved
              ? "Preservation checks passed."
              : "Preservation checks reported a violation."}{" "}
            Unchanged sections: {review.preservation.unchanged_section_count}. Changed sections:{" "}
            {review.preservation.changed_section_count}.
          </p>
        </article>
      ) : null}
      <div className="actions" style={{ marginTop: "1rem" }}>
        <button type="button" className="primary" onClick={() => void apply()} disabled={busy || !decided}>
          Apply decided updates
        </button>
      </div>
    </section>
  );
}
