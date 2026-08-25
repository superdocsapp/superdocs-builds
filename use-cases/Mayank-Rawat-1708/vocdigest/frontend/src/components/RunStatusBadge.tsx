/**
 * @file src/components/RunStatusBadge.tsx
 * @description Colour-coded pill for a run's status. Colour encodes whether the run
 *   needs attention (amber), is working (blue), finished (green) or broke (red), so the
 *   dashboard is scannable without reading every label.
 * @flow status -> lookup table -> styled span
 * @dependencies clsx for conditional classes
 */
import clsx from "clsx";
import type { RunStatus } from "../lib/api";

const STYLES: Record<string, string> = {
  COMPLETE: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  FAILED: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  AWAITING_APPROVAL: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  PAUSED: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  PENDING: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  CANCELLED: "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-400",
};
const WORKING = "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300";

export function RunStatusBadge({ status, className }: { status: RunStatus; className?: string }) {
  const style = STYLES[status] ?? WORKING;
  const isWorking = !(status in STYLES);
  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium", style, className)}>
      {isWorking && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />}
      {status.replace(/_/g, " ")}
    </span>
  );
}