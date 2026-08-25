/**
 * @file src/components/QuoteCard.tsx
 * @description Displays an anonymized quote and, crucially, what was removed from it.
 *   Uncertain spans are highlighted rather than hidden — the reviewer's job is to
 *   resolve exactly those, so burying them would defeat the gate.
 * @flow Quote -> redaction placeholders highlighted inline -> optional redaction detail
 * @dependencies lucide-react, clsx
 */
import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, Eye, EyeOff } from "lucide-react";
import type { Quote } from "../lib/api";

const PLACEHOLDER = /(\[USER\]|\[EMAIL\]|\[COMPANY\]|\[ID\]|\[PHONE\]|\[URL\]|\[POSSIBLE-NAME\]|\[REDACTED[^\]]*\])/g;

/** Highlight redaction markers so a reader can see what was taken out and where. */
function renderWithMarkers(text: string) {
  return text.split(PLACEHOLDER).map((part, i) =>
    PLACEHOLDER.test(part) ? (
      <mark
        key={i}
        className={clsx(
          "px-1 rounded font-mono text-xs",
          part === "[POSSIBLE-NAME]"
            ? "bg-amber-200 text-amber-900 dark:bg-amber-500/30 dark:text-amber-200"
            : "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
        )}
      >
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

export function QuoteCard({ quote, showSource = false }: { quote: Quote; showSource?: boolean }) {
  const [showRedactions, setShowRedactions] = useState(false);

  return (
    <div className={clsx("card p-4", quote.needs_review && "ring-1 ring-amber-400/60")}>
      <blockquote className="text-sm leading-relaxed">
        “{renderWithMarkers(quote.anonymized)}”
      </blockquote>

      <div className="mt-3 flex items-center gap-3 flex-wrap text-xs text-slate-500">
        {quote.date && <span>{quote.date}</span>}
        {showSource && <span className="font-mono">{quote.citation}</span>}
        <span>{quote.redaction_count} redaction{quote.redaction_count === 1 ? "" : "s"}</span>
        {quote.redactions.length > 0 && (
          <button
            onClick={() => setShowRedactions((v) => !v)}
            className="inline-flex items-center gap-1 hover:text-accent transition"
          >
            {showRedactions ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
            {showRedactions ? "Hide" : "Show"} what was removed
          </button>
        )}
      </div>

      {quote.needs_review && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 p-3">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-xs text-amber-900 dark:text-amber-200">
            <p className="font-medium">Uncertain redaction — needs your decision</p>
            <p className="mt-0.5">
              Could not classify with confidence:{" "}
              <span className="font-mono">{quote.uncertain_spans.join(", ")}</span>
            </p>
          </div>
        </div>
      )}

      {showRedactions && (
        <ul className="mt-3 space-y-1 border-t border-slate-100 dark:border-slate-800 pt-3">
          {quote.redactions.map((r, i) => (
            <li key={i} className="text-xs flex items-center gap-2 font-mono">
              <span className="text-slate-400 line-through">{r.original}</span>
              <span className="text-slate-400">→</span>
              <span className="text-slate-700 dark:text-slate-300">{r.replacement}</span>
              <span className="ml-auto text-slate-400">
                {r.method} · {(r.confidence * 100).toFixed(0)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
