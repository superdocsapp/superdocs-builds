import { useQueueStore } from "@/stores/queueStore";
import type { SortField } from "@/types/review";

const SORT_FIELD_OPTIONS: { value: SortField; label: string }[] = [
  { value: "queued_at", label: "Queued At" },
  { value: "item_type", label: "Item Type" },
];

export function QueueSortControls() {
  const sortBy = useQueueStore((s) => s.sortBy);
  const sortDirection = useQueueStore((s) => s.sortDirection);
  const setSortBy = useQueueStore((s) => s.setSortBy);

  const handleFieldChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as SortField;
    setSortBy(value, sortDirection);
  };

  const handleDirectionToggle = () => {
    const newDirection = sortDirection === "asc" ? "desc" : "asc";
    setSortBy(sortBy, newDirection);
  };

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Sort by field"
        value={sortBy}
        onChange={handleFieldChange}
        className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {SORT_FIELD_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        aria-label="Sort direction"
        onClick={handleDirectionToggle}
        className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-gray-200 hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {sortDirection === "asc" ? "↑ Asc" : "↓ Desc"}
      </button>
    </div>
  );
}

export default QueueSortControls;
