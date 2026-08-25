/**
 * @file src/components/ThemeCard.tsx
 * @description A theme with its volume, trend, quotes and evidence. Evidence citations
 *   are shown rather than summarised so every claim can be traced to a source line —
 *   that traceability is the point, not decoration.
 * @flow Theme -> header with trend chip -> quotes -> expandable evidence citation list
 * @dependencies lucide-react, clsx, QuoteCard
 */
import { useState } from "react";
import clsx from "clsx";
import { TrendingUp, TrendingDown, Minus, Sparkles, HelpCircle, FileText } from "lucide-react";
import type { Theme } from "../lib/api";
import { QuoteCard } from "./QuoteCard";

const TREND = {
  GREW: { icon: TrendingUp, cls: "text-red-600 bg-red-50 dark:bg-red-900/30", label: "Grew" },
  SHRANK: { icon: TrendingDown, cls: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30", label: "Shrank" },
  STABLE: { icon: Minus, cls: "text-slate-600 bg-slate-100 dark:bg-slate-800", label: "Stable" },
  NEW: { icon: Sparkles, cls: "text-blue-600 bg-blue-50 dark:bg-blue-900/30", label: "New" },
  RESOLVED: { icon: TrendingDown, cls: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30", label: "Resolved" },
  UNKNOWN: { icon: HelpCircle, cls: "text-slate-500 bg-slate-100 dark:bg-slate-800", label: "No comparison" },
};

export function ThemeCard({ theme, rank }: { theme: Theme; rank?: number }) {
  const [showEvidence, setShowEvidence] = useState(false);
  const trend = TREND[theme.volume_trend] ?? TREND.UNKNOWN;
  const Icon = trend.icon;
  const pct = theme.growth_rate != null ? Math.round(theme.growth_rate * 100) : null;

  return (
    <article className="card p-5">
      <header className="flex items-start gap-3">
        {rank != null && (
          <span className="text-xs font-semibold text-slate-400 tabular-nums mt-1">#{rank}</span>
        )}
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold">{theme.name}</h3>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">{theme.description}</p>
        </div>
        <span className={clsx("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0", trend.cls)}>
          <Icon className="w-3.5 h-3.5" />
          {trend.label}
          {pct != null && <span className="tabular-nums">{pct > 0 ? "+" : ""}{pct}%</span>}
        </span>
      </header>

      <div className="mt-4 flex items-center gap-4 text-sm">
        <span><strong className="tabular-nums">{theme.volume_count}</strong> conversations</span>
        <span className="text-slate-500 tabular-nums">{(theme.volume_share * 100).toFixed(1)}% of volume</span>
        {theme.prior_quarter_count != null && (
          <span className="text-slate-500 tabular-nums">was {theme.prior_quarter_count}</span>
        )}
      </div>

      {theme.confidence_note && (
        <p className="mt-3 text-xs rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-900 dark:text-amber-200 p-3">
          {theme.confidence_note}
        </p>
      )}

      {theme.representative_quotes.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">What customers said</p>
          {theme.representative_quotes.map((q) => <QuoteCard key={q.conversation_id} quote={q} />)}
        </div>
      )}

      <button
        onClick={() => setShowEvidence((v) => !v)}
        className="mt-4 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
      >
        <FileText className="w-3.5 h-3.5" />
        {showEvidence ? "Hide" : "Show"} {theme.evidence_refs.length} evidence citation
        {theme.evidence_refs.length === 1 ? "" : "s"}
      </button>

      {showEvidence && (
        <ul className="mt-2 grid grid-cols-2 md:grid-cols-3 gap-1 text-xs font-mono text-slate-500">
          {theme.evidence_refs.map((ref, i) => (
            <li key={ref.conversation_id} className="truncate">[{i + 1}] {ref.citation}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
