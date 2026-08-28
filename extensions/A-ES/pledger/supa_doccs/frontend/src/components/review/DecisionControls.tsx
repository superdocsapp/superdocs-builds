import { useState, useCallback } from "react";
import type { QueueItem } from "@/types/review";

export interface DecisionControlsProps {
  item: QueueItem;
  onDecide: (decision: "approved" | "rejected", justification: string) => void;
  isSubmitting: boolean;
}

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

/**
 * Renders Approve/Reject buttons with a justification textarea.
 * Buttons are only visible when item status is "pending".
 * Submission is blocked when justification is empty or whitespace-only.
 * Includes a sweep animation on decision before advancing.
 */
export function DecisionControls({
  item,
  onDecide,
  isSubmitting,
}: DecisionControlsProps) {
  const [justification, setJustification] = useState("");
  const [sweepColor, setSweepColor] = useState<"emerald" | "rose" | null>(null);

  const isPending = item.status === "pending";
  const trimmed = justification.trim();
  const canSubmit = trimmed.length > 0 && !isSubmitting;

  const handleDecide = useCallback(
    (decision: "approved" | "rejected") => {
      if (!canSubmit) return;
      // Trigger sweep animation
      setSweepColor(decision === "approved" ? "emerald" : "rose");
      // After animation completes, submit
      setTimeout(() => {
        onDecide(decision, trimmed);
        setJustification("");
        setSweepColor(null);
      }, 400);
    },
    [canSubmit, onDecide, trimmed]
  );

  if (!isPending) {
    const isRecheck = item.status === "approved_needs_recheck";
    return (
      <section aria-label="Decision controls">
        <p className="text-sm text-white/50">
          Decision:{" "}
          <span
            className={`font-medium capitalize ${
              isRecheck
                ? "text-amber-300"
                : item.decision === "rejected"
                  ? "text-rose-400"
                  : "text-emerald-400"
            }`}
          >
            {isRecheck ? "approved — needs recheck" : (item.decision ?? item.status)}
          </span>
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Decision controls"
      className="relative rounded-xl border border-white/[0.06] bg-surface-elevated p-4 overflow-hidden"
    >
      {/* Sweep overlay animation */}
      {sweepColor && (
        <div
          className={`absolute inset-0 decision-sweep pointer-events-none ${
            sweepColor === "emerald" ? "bg-emerald-500/20" : "bg-rose-500/20"
          }`}
          aria-hidden="true"
        />
      )}

      <h3 className="mb-3 text-xs font-medium uppercase tracking-wider text-white/40">
        Decision
      </h3>
      <div className="space-y-4 relative">
        <div>
          <textarea
            aria-label="Decision justification"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            placeholder="Provide justification for your decision…"
            disabled={isSubmitting}
            className="w-full rounded-lg border border-white/[0.08] bg-surface-base px-3 py-2.5 text-sm text-white/80 placeholder-white/25 transition-all focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:shadow-lg focus:shadow-indigo-500/5 disabled:opacity-50"
            rows={3}
          />
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => handleDecide("approved")}
            disabled={!canSubmit}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/25 transition-all hover:bg-emerald-400 hover:shadow-emerald-500/30 hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:ring-offset-2 focus:ring-offset-surface-elevated disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100 disabled:hover:bg-emerald-500 disabled:shadow-none"
          >
            {isSubmitting && <Spinner />}
            Approve
          </button>
          <button
            type="button"
            onClick={() => handleDecide("rejected")}
            disabled={!canSubmit}
            className="inline-flex items-center gap-2 rounded-lg bg-rose-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-rose-500/25 transition-all hover:bg-rose-400 hover:shadow-rose-500/30 hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-rose-400 focus:ring-offset-2 focus:ring-offset-surface-elevated disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100 disabled:hover:bg-rose-500 disabled:shadow-none"
          >
            {isSubmitting && <Spinner />}
            Reject
          </button>
        </div>
      </div>
    </section>
  );
}
