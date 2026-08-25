/**
 * @file src/pages/ApprovalGate.tsx
 * @description The human gate. Items are grouped by type, with quotes needing review
 *   surfaced first because they are the only ones with a real leak risk. Nothing is
 *   pre-decided: the submit button stays disabled until every item has a choice, so a
 *   reviewer cannot accidentally publish something they never looked at.
 * @flow load queue -> reviewer marks each item -> submit posts approved/rejected ids ->
 *   run resumes automatically once nothing is pending
 * @dependencies lib/api, ApprovalItemCard
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertCircle, CheckCheck, Loader2, ShieldAlert } from "lucide-react";
import { api, type ApprovalQueue } from "../lib/api";
import { ApprovalItemCard } from "../components/ApprovalItem";

type Decision = "approved" | "rejected" | null;
const ORDER = ["QUOTE", "THEME", "FINDING", "UPDATE"];

export default function ApprovalGate() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [queue, setQueue] = useState<ApprovalQueue | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    void api.getApprovalItems(runId).then(setQueue).catch((e) => setError((e as Error).message));
  }, [runId]);

  const pendingItems = useMemo(() => {
    if (!queue) return [];
    return ORDER.flatMap((type) => (queue.groups[type] ?? []).filter((i) => i.status === "PENDING"));
  }, [queue]);

  const undecided = pendingItems.filter((i) => !decisions[i.id]).length;

  const submit = async () => {
    if (!runId) return;
    setSubmitting(true); setError(null);
    const approved = Object.entries(decisions).filter(([, d]) => d === "approved").map(([id]) => id);
    const rejected = Object.entries(decisions).filter(([, d]) => d === "rejected").map(([id]) => id);
    try {
      await api.submitDecisions(runId, approved, rejected);
      navigate(`/runs/${runId}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  const approveAll = async () => {
    if (!runId) return;
    setSubmitting(true);
    try {
      await api.approveAll(runId);
      navigate(`/runs/${runId}`);
    } catch (e) {
      setError((e as Error).message);
      setSubmitting(false);
    }
  };

  if (error && !queue) return (
    <div className="card p-6 flex items-center gap-3 text-red-600"><AlertCircle className="w-5 h-5" /> {error}</div>
  );
  if (!queue) return (
    <div className="flex items-center gap-2 text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading review queue…</div>
  );

  if (!queue.gate_open) return (
    <div className="card p-12 text-center">
      <CheckCheck className="w-10 h-10 mx-auto text-emerald-600" />
      <h2 className="mt-4 font-semibold">Nothing left to review</h2>
      <p className="mt-1 text-sm text-slate-500">
        {queue.approved} approved, {queue.rejected} rejected.
      </p>
      <button onClick={() => navigate(`/runs/${runId}`)} className="btn-primary mt-6">Back to run</button>
    </div>
  );

  const quotesNeedingReview = (queue.groups.QUOTE ?? []).filter((i) => i.status === "PENDING").length;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Review before publishing</h1>
        <p className="mt-1 text-sm text-slate-500">
          {queue.pending} item{queue.pending === 1 ? "" : "s"} pending. Rejecting an item removes that content
          from the digest — the rest still publishes.
        </p>
      </header>

      {quotesNeedingReview > 0 && (
        <div className="card p-4 flex items-start gap-3 border-amber-300">
          <ShieldAlert className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium">{quotesNeedingReview} quote{quotesNeedingReview === 1 ? "" : "s"} have uncertain redactions</p>
            <p className="text-slate-600 dark:text-slate-400 mt-0.5">
              Spans marked <span className="font-mono text-xs">[POSSIBLE-NAME]</span> could not be classified
              confidently. Anonymization is not guaranteed — this review is the control.
            </p>
          </div>
        </div>
      )}

      <div className="sticky top-16 z-10 card p-3 flex items-center gap-3 backdrop-blur bg-white/90 dark:bg-slate-900/90">
        <span className="text-sm">
          <strong className="tabular-nums">{pendingItems.length - undecided}</strong> of{" "}
          <strong className="tabular-nums">{pendingItems.length}</strong> decided
        </span>
        <div className="flex-1" />
        <button onClick={approveAll} disabled={submitting} className="btn-ghost text-sm">Approve all</button>
        <button onClick={submit} disabled={submitting || undecided > 0} className="btn-primary text-sm">
          {submitting ? <><Loader2 className="w-4 h-4 animate-spin" /> Submitting…</>
            : undecided > 0 ? `${undecided} left to decide` : "Submit and continue"}
        </button>
      </div>

      {error && <div className="card p-4 text-sm text-red-600">{error}</div>}

      {ORDER.map((type) => {
        const items = (queue.groups[type] ?? []).filter((i) => i.status === "PENDING");
        if (items.length === 0) return null;
        return (
          <section key={type} className="space-y-3">
            <h2 className="font-semibold text-sm uppercase tracking-wide text-slate-500">
              {type} ({items.length})
            </h2>
            {items.map((item) => (
              <ApprovalItemCard
                key={item.id}
                item={item}
                decision={decisions[item.id] ?? null}
                onDecide={(choice) => setDecisions((prev) => ({ ...prev, [item.id]: choice }))}
              />
            ))}
          </section>
        );
      })}
    </div>
  );
}
