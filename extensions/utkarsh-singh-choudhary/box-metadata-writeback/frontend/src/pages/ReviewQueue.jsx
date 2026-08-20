import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ConfidenceValue, EmptyState, Loading } from "../components/bits.jsx";

export default function ReviewQueue({ onOpenFile, onDecided }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = () => {
    api.reviews().then(setData).catch((e) => setErr(e.message));
  };
  useEffect(load, []);

  const decide = async (reviewId, approve) => {
    setBusyId(reviewId);
    try {
      await (approve ? api.approveReview(reviewId) : api.rejectReview(reviewId));
      load();
      onDecided?.();
    } finally {
      setBusyId(null);
    }
  };

  if (err) return <EmptyState title="Can't reach the workflow API" body={err} />;
  if (!data) return <Loading />;

  return (
    <div>
      <div className="page-header">
        <div>
          <p className="eyebrow">Human gate</p>
          <h1 className="page-title">Review queue</h1>
          <p className="page-sub">
            Fields extracted below the {Math.round(data.threshold * 100)}% confidence threshold. Nothing here
            reaches Box metadata until a person approves it.
          </p>
        </div>
      </div>

      {data.pending.length === 0 ? (
        <EmptyState title="Queue is empty" body="Every extracted field met the confidence bar, or was already decided." />
      ) : (
        data.pending.map((r) => (
          <div className="review-card" key={r.review_id}>
            <div className="review-card-head">
              <div>
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-faint)" }}>
                  {r.file_id} · {r.field_name.replaceAll("_", " ")}
                </div>
                <div className="review-value">{r.proposed_value}</div>
              </div>
              <ConfidenceValue value={r.confidence} />
            </div>
            <div className="review-actions">
              <button className="btn btn-success btn-sm" disabled={busyId === r.review_id} onClick={() => decide(r.review_id, true)}>
                Approve
              </button>
              <button className="btn btn-danger btn-sm" disabled={busyId === r.review_id} onClick={() => decide(r.review_id, false)}>
                Reject
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => onOpenFile(r.file_id)}>
                Open document →
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
