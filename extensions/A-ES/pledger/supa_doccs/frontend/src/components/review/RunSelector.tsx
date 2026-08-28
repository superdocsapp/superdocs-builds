import * as Select from "@radix-ui/react-select";
import type { RunSummary } from "@/types/review";

interface RunSelectorProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}

const STATUS_DOT_COLORS: Record<RunSummary["status"], string> = {
  running: "bg-blue-400",
  completed: "bg-emerald-400",
  failed: "bg-rose-400",
  paused: "bg-amber-400",
};

function formatRunId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RunSelector({ runs, selectedRunId, onSelectRun }: RunSelectorProps) {
  return (
    <Select.Root value={selectedRunId ?? undefined} onValueChange={onSelectRun}>
      <Select.Trigger
        aria-label="Select pipeline run"
        className="inline-flex items-center gap-2 rounded-lg border border-white/[0.08] bg-surface-elevated px-3 py-2 text-sm text-white/80 transition-all hover:border-white/[0.15] hover:bg-surface-elevated/80 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
      >
        <Select.Value placeholder="Select a run" />
        <Select.Icon className="text-white/40">
          <ChevronDownIcon />
        </Select.Icon>
      </Select.Trigger>

      <Select.Portal>
        <Select.Content
          className="overflow-hidden rounded-lg border border-white/[0.08] bg-surface-card shadow-2xl shadow-black/40 backdrop-blur-xl"
          position="popper"
          sideOffset={4}
        >
          <Select.Viewport className="p-1">
            <Select.Item
              value="all"
              className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm text-white/70 outline-none transition-colors data-[highlighted]:bg-white/[0.06] data-[highlighted]:text-white border-b border-white/[0.06] mb-1"
            >
              <span
                className="h-2 w-2 rounded-full bg-indigo-400"
                aria-hidden="true"
              />
              <Select.ItemText>All pending</Select.ItemText>
              <span className="ml-auto text-xs text-white/30">cross-run</span>
            </Select.Item>
            {runs.map((run) => (
              <Select.Item
                key={run.id}
                value={run.id}
                className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm text-white/70 outline-none transition-colors data-[highlighted]:bg-white/[0.06] data-[highlighted]:text-white"
              >
                <span
                  className={`h-2 w-2 rounded-full ${STATUS_DOT_COLORS[run.status]}`}
                  aria-hidden="true"
                />
                <Select.ItemText>
                  {formatRunId(run.id)}
                </Select.ItemText>
                <span className="ml-auto text-xs text-white/30">
                  {formatTimestamp(run.started_at)}
                </span>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

function ChevronDownIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        d="M3 4.5L6 7.5L9 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default RunSelector;
