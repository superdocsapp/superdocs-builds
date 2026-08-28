import type { QueueItem, ItemType } from "@/types/review";

interface PayloadViewProps {
  item: QueueItem;
}

const ITEM_TYPE_LABELS: Record<string, string> = {
  finding: "FINDING",
  conflict: "CONFLICT",
  proposed_update: "UPDATE",
};

const TYPE_GRADIENT: Record<ItemType, string> = {
  finding: "from-rose-500/10 via-rose-900/5 to-transparent",
  conflict: "from-amber-500/10 via-amber-900/5 to-transparent",
  proposed_update: "from-violet-500/10 via-violet-900/5 to-transparent",
};

const TYPE_BADGE_STYLE: Record<ItemType, string> = {
  finding: "bg-rose-500/15 text-rose-300 border-rose-500/20",
  conflict: "bg-amber-500/15 text-amber-300 border-amber-500/20",
  proposed_update: "bg-violet-500/15 text-violet-300 border-violet-500/20",
};

/**
 * Renders the full payload details of a queue item including summary,
 * item_type badge, queued_at date, status, and details key-value pairs.
 */
export function PayloadView({ item }: PayloadViewProps) {
  const formattedDate = new Date(item.queued_at).toLocaleString();
  const gradient = TYPE_GRADIENT[item.item_type];
  const badgeStyle = TYPE_BADGE_STYLE[item.item_type];

  return (
    <section aria-label="Item payload details">
      {/* Gradient backdrop header */}
      <div className={`-mx-4 -mt-4 px-4 pt-4 pb-4 bg-gradient-to-b ${gradient}`}>
        {/* Summary heading */}
        <h2 className="text-base font-semibold tracking-tight text-white/90">
          {item.payload.summary}
        </h2>

        {/* Metadata row */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${badgeStyle}`}>
            {ITEM_TYPE_LABELS[item.item_type] ?? item.item_type}
          </span>
          <span className="inline-flex items-center gap-1.5 text-[11px] text-white/50">
            <span className={`h-1.5 w-1.5 rounded-full ${
              item.status === "approved"
                ? "bg-emerald-400"
                : item.status === "rejected"
                  ? "bg-rose-400"
                  : item.status === "approved_needs_recheck"
                    ? "bg-amber-400"
                    : "bg-white/30"
            }`} aria-hidden="true" />
            {item.status === "approved_needs_recheck" ? "approved · needs recheck" : item.status}
          </span>
          <span className="text-xs text-white/40 uppercase tracking-wider">
            Queued: {formattedDate}
          </span>
        </div>
      </div>

      {/* Details as key-value pairs */}
      {Object.keys(item.payload.details).length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-white/40">Details</h3>
          <dl className="space-y-1.5 rounded-lg border border-white/[0.06] bg-surface-card p-3">
            {Object.entries(item.payload.details).map(([key, value]) => (
              <div key={key} className="flex gap-2 text-sm">
                <dt className="font-mono text-white/30 text-xs">{key}:</dt>
                <dd className="text-white/70 leading-relaxed">
                  {typeof value === "string" || typeof value === "number"
                    ? String(value)
                    : JSON.stringify(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
