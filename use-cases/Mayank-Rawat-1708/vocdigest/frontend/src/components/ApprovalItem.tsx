/**
 * @file src/components/ApprovalItem.tsx
 * @description One reviewable item with approve/reject controls. Rejecting is presented
 *   as removing that piece of content, not as failing the run, because that is exactly
 *   what happens — the digest still exports without it.
 * @flow item + decision state -> type-specific body -> approve/reject buttons that
 *   report the choice upward
 * @dependencies lucide-react, clsx, QuoteCard
 */
import clsx from "clsx";
import { Check, X, AlertTriangle } from "lucide-react";
import type { ApprovalItem as Item } from "../lib/api";
import { QuoteCard } from "./QuoteCard";

const TYPE_LABEL: Record<string, string> = {
  THEME: "Theme",
  QUOTE: "Quote needing review",
  FINDING: "Finding",
  UPDATE: "Comparison update",
};

export function ApprovalItemCard({
  item, decision, onDecide,
}: {
  item: Item;
  decision: "approved" | "rejected" | null;
  onDecide: (choice: "approved" | "rejected" | null) => void;
}) {
  const c = item.content ?? {};

  return (
    <div className={clsx(
      "card p-5 transition",
      decision === "approved" && "ring-2 ring-emerald-400",
      decision === "rejected" && "ring-2 ring-red-400 opacity-70",
    )}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            {TYPE_LABEL[item.item_type] ?? item.item_type}
          </span>

          {item.item_type === "THEME" && (
            <>
              <h4 className="font-semibold mt-1">{c.name}</h4>
              <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">{c.description}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                <span><strong className="tabular-nums">{c.volume}</strong> conversations</span>
                <span>{c.trend}</span>
                {c.prior_count != null && <span className="tabular-nums">was {c.prior_count}</span>}
                <span className="tabular-nums">{c.evidence_count} citations</span>
              </div>
              {c.confidence_note && (
                <p className="mt-2 flex items-start gap-2 text-xs rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-900 dark:text-amber-200 p-2.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  {c.confidence_note}
                </p>
              )}
            </>
          )}

          {item.item_type === "QUOTE" && (
            <div className="mt-2">
              <QuoteCard
                quote={{
                  conversation_id: item.id,
                  citation: c.citation ?? "",
                  date: null,
                  anonymized: c.anonymized ?? "",
                  redaction_count: (c.redactions ?? []).length,
                  redactions: c.redactions ?? [],
                  uncertain_spans: c.uncertain_spans ?? [],
                  needs_review: true,
                }}
                showSource
              />
              <p className="mt-2 text-xs text-slate-500">{c.reason}</p>
            </div>
          )}

          {(item.item_type === "FINDING" || item.item_type === "UPDATE") && (
            <>
              <h4 className="font-semibold mt-1">{c.title}</h4>
              <pre className="mt-2 text-xs whitespace-pre-wrap font-sans text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/60 rounded-lg p-3 max-h-56 overflow-auto">
                {c.instruction_preview}
              </pre>
            </>
          )}
        </div>

        <div className="flex flex-col gap-2 shrink-0">
          <button
            onClick={() => onDecide(decision === "approved" ? null : "approved")}
            className={clsx("btn text-xs py-1.5 px-3",
              decision === "approved"
                ? "bg-emerald-600 text-white"
                : "border border-emerald-300 text-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-900/20")}
          >
            <Check className="w-3.5 h-3.5" /> Approve
          </button>
          <button
            onClick={() => onDecide(decision === "rejected" ? null : "rejected")}
            className={clsx("btn text-xs py-1.5 px-3",
              decision === "rejected"
                ? "bg-red-600 text-white"
                : "border border-red-300 text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20")}
          >
            <X className="w-3.5 h-3.5" /> Reject
          </button>
        </div>
      </div>
    </div>
  );
}
