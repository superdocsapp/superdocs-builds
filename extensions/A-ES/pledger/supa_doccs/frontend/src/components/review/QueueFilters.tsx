import { useQueueStore } from "@/stores/queueStore";
import type { ItemType } from "@/types/review";

const ITEM_TYPE_OPTIONS: { value: ItemType | ""; label: string }[] = [
  { value: "", label: "All Types" },
  { value: "finding", label: "Finding" },
  { value: "conflict", label: "Conflict" },
  { value: "proposed_update", label: "Proposed Update" },
];

export function QueueFilters() {
  const filters = useQueueStore((s) => s.filters);
  const setFilters = useQueueStore((s) => s.setFilters);

  const handleTypeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as ItemType | "";
    setFilters({
      ...filters,
      itemType: value === "" ? null : value,
    });
  };

  const handleUnverifiableChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilters({
      ...filters,
      unverifiableOnly: e.target.checked,
    });
  };

  return (
    <div className="flex items-center gap-3">
      <select
        aria-label="Filter by item type"
        value={filters.itemType ?? ""}
        onChange={handleTypeChange}
        className="rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {ITEM_TYPE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-1.5 text-xs text-gray-300">
        <input
          type="checkbox"
          aria-label="Show unverifiable only"
          checked={filters.unverifiableOnly}
          onChange={handleUnverifiableChange}
          className="h-3.5 w-3.5 rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-2 focus:ring-blue-500"
        />
        Unverifiable only
      </label>
    </div>
  );
}

export default QueueFilters;
