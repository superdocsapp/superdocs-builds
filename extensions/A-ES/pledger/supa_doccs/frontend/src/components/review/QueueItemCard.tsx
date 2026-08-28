import { QueueItem, ItemType } from "@/types/review";
import { itemIsUnverifiable } from "@/utils/citationHelpers";

export interface QueueItemCardProps {
  item: QueueItem;
  isSelected: boolean;
  isLoading: boolean;
  onClick: () => void;
}

const ITEM_TYPE_LABELS: Record<string, string> = {
  finding: "FINDING",
  conflict: "CONFLICT",
  proposed_update: "UPDATE",
};

const TYPE_COLORS: Record<ItemType, { border: string; glow: string; icon: string; bg: string }> = {
  finding: {
    border: "border-l-rose-500",
    glow: "hover:shadow-rose-500/20 hover:shadow-lg",
    icon: "text-rose-400",
    bg: "hover:bg-rose-900/10",
  },
  conflict: {
    border: "border-l-amber-500",
    glow: "hover:shadow-amber-500/20 hover:shadow-lg",
    icon: "text-amber-400",
    bg: "hover:bg-amber-900/10",
  },
  proposed_update: {
    border: "border-l-violet-500",
    glow: "hover:shadow-violet-500/20 hover:shadow-lg",
    icon: "text-violet-400",
    bg: "hover:bg-violet-900/10",
  },
};

const TYPE_SELECTED: Record<ItemType, string> = {
  finding: "ring-2 ring-rose-500/50 shadow-lg shadow-rose-500/10 scale-[1.01]",
  conflict: "ring-2 ring-amber-500/50 shadow-lg shadow-amber-500/10 scale-[1.01]",
  proposed_update: "ring-2 ring-violet-500/50 shadow-lg shadow-violet-500/10 scale-[1.01]",
};

function TypeIcon({ type, className }: { type: ItemType; className?: string }) {
  switch (type) {
    case "finding":
      return (
        <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 1L1 14h14L8 1z" />
          <path strokeLinecap="round" d="M8 6v3M8 11.5v.5" />
        </svg>
      );
    case "conflict":
      return (
        <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 2L10 6l4.5.5-3.25 3L12 14l-4-2.5L4 14l.75-4.5L1.5 6.5 6 6l2-4z" />
        </svg>
      );
    case "proposed_update":
      return (
        <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M11.5 1.5l3 3-8.5 8.5H3v-3l8.5-8.5z" />
          <path strokeLinecap="round" d="M9.5 3.5l3 3" />
        </svg>
      );
  }
}

function StatusDot({ status }: { status: string }) {
  const isRecheck = status === "approved_needs_recheck";

  const dotColor =
    status === "approved"
      ? "bg-emerald-400 shadow-emerald-400/50"
      : status === "rejected"
        ? "bg-rose-400 shadow-rose-400/50"
        : isRecheck
          ? "bg-amber-400 shadow-amber-400/50"
          : "bg-white/30";

  const textColor =
    status === "approved"
      ? "text-emerald-400"
      : status === "rejected"
        ? "text-rose-400 line-through"
        : isRecheck
          ? "text-amber-300"
          : "text-white/60";

  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[11px] ${textColor}`}
      title={
        isRecheck
          ? "Approved with zero/null citations — flagged for re-review (migration 015)"
          : undefined
      }
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotColor} shadow-sm`} aria-hidden="true" />
      {isRecheck ? "approved · needs recheck" : status}
    </span>
  );
}

export function QueueItemCard({
  item,
  isSelected,
  isLoading,
  onClick,
}: QueueItemCardProps) {
  const summary = item.payload.summary;
  const truncatedSummary =
    summary.length > 80 ? `${summary.slice(0, 80)}…` : summary;

  const typeStyle = TYPE_COLORS[item.item_type];
  const selectedStyle = isSelected ? TYPE_SELECTED[item.item_type] : "";

  const hasUnverifiable = itemIsUnverifiable(item.payload.source_citations);

  return (
    <div
      role="option"
      aria-selected={isSelected}
      aria-busy={isLoading}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      tabIndex={0}
      data-type-color={item.item_type}
      className={`
        relative cursor-pointer rounded-lg border border-white/[0.06] border-l-[3px]
        ${typeStyle.border} bg-surface-card p-3 transition-all duration-200
        ${typeStyle.glow} ${typeStyle.bg}
        focus:outline-none focus:ring-2 focus:ring-indigo-500/50
        ${selectedStyle}
      `}
    >
      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-end rounded-lg bg-surface-base/60 pr-3 backdrop-blur-sm">
          <svg
            className="h-5 w-5 animate-spin text-indigo-400"
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
        </div>
      )}

      {/* Header row: icon + type + status + unverifiable indicator */}
      <div className="flex items-center gap-2">
        <TypeIcon type={item.item_type} className={`h-4 w-4 ${typeStyle.icon}`} />
        <span className="text-base font-semibold tracking-tight text-white/90 flex-1 truncate">
          {truncatedSummary}
        </span>
        {hasUnverifiable && (
          <span className="h-2 w-2 rounded-full bg-amber-400 warning-pulse" title="Has unverifiable citations" />
        )}
      </div>

      {/* Status row */}
      <div className="mt-2 flex items-center justify-between">
        <StatusDot status={item.status} />
        <span className="text-[10px] text-white/30 font-bold uppercase tracking-wider">
          {ITEM_TYPE_LABELS[item.item_type] ?? item.item_type}
        </span>
      </div>
    </div>
  );
}
