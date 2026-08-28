import type { RunSummary } from "@/types/review";
import { RunSelector } from "./RunSelector";
import { StatusBadge } from "./StatusBadge";
import { ResumeButton } from "./ResumeButton";

interface TopBarProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  runStatus: "running" | "completed" | "failed" | "paused";
  onSelectRun: (runId: string) => void;
  /** Whether the run can be resumed (paused or failed) */
  canResume?: boolean;
  /** Whether a resume request is in-flight */
  isResuming?: boolean;
  /** Callback to trigger run resume */
  onResume?: () => void;
}

export function TopBar({
  runs,
  selectedRunId,
  runStatus,
  onSelectRun,
  canResume = false,
  isResuming = false,
  onResume,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-40 flex items-center justify-between gap-4 border-b border-white/[0.06] bg-white/[0.03] px-5 py-3 backdrop-blur-xl">
      {/* Left: selector + status */}
      <div className="flex items-center gap-3">
        <RunSelector
          runs={runs}
          selectedRunId={selectedRunId}
          onSelectRun={onSelectRun}
        />
        <StatusBadge status={runStatus} />
        {onResume && (
          <ResumeButton
            canResume={canResume}
            isResuming={isResuming}
            onResume={onResume}
          />
        )}
      </div>

      {/* Right: pipeline summary counts */}
      <div className="hidden items-center gap-3 text-xs text-white/40 sm:flex">
        <span className="uppercase tracking-wider">Pipeline</span>
        <span className="h-3 w-px bg-white/10" aria-hidden="true" />
        <span className="text-white/60 font-medium capitalize">{runStatus}</span>
      </div>
    </header>
  );
}

export default TopBar;
