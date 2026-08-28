import { QueueItem } from "@/types/review";
import { QueueItemCard } from "./QueueItemCard";
import { QueueSummaryBar } from "./QueueSummaryBar";

export interface QueueListProps {
  items: QueueItem[];
  selectedItemId: string | null;
  optimisticStatuses: Record<string, string>;
  onSelectItem: (itemId: string) => void;
}

export interface QueueListFullProps extends QueueListProps {
  total: number;
  pending: number;
}

export function QueueList({
  items,
  selectedItemId,
  optimisticStatuses,
  onSelectItem,
  total,
  pending,
}: QueueListFullProps) {
  return (
    <div className="flex h-full flex-col bg-surface-base">
      <QueueSummaryBar total={total} pending={pending} />
      <div
        role="listbox"
        aria-label="Approval queue items"
        className="flex-1 space-y-2 overflow-y-auto p-3"
      >
        {items.map((item, index) => (
          <div
            key={item.id}
            className="animate-stagger"
            style={{ "--index": index } as React.CSSProperties}
          >
            <QueueItemCard
              item={item}
              isSelected={item.id === selectedItemId}
              isLoading={item.id in optimisticStatuses}
              onClick={() => onSelectItem(item.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
