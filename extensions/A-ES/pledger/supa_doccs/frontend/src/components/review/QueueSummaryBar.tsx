export interface QueueSummaryBarProps {
  total: number;
  pending: number;
}

export function QueueSummaryBar({ total, pending }: QueueSummaryBarProps) {
  const decided = total - pending;

  return (
    <div
      className="mx-3 mt-3 mb-2 flex items-center gap-2 rounded-full bg-white/[0.03] border border-white/[0.06] px-4 py-1.5 text-xs"
      aria-live="polite"
    >
      <span className="text-white/60 font-medium">{pending} pending</span>
      <span className="h-3 w-px bg-white/10" aria-hidden="true" />
      <span className="text-emerald-400/70">{decided} decided</span>
      <span className="ml-auto text-white/30">{total} total</span>
    </div>
  );
}
