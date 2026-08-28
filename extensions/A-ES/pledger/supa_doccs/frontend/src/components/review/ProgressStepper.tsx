import { deriveStageStatus, type StageStatus } from "@/utils/stageDerivation";
import { STAGES, type StageDefinition } from "@/utils/constants";

export interface ProgressStepperProps {
  completedNodes: string[];
  currentNode: string | null;
}

function StageIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case "complete":
      return (
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/15 border border-emerald-500/30"
          aria-hidden="true"
        >
          <svg
            className="h-4 w-4 text-emerald-400 draw-check"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 8.5L6.5 12L13 4" />
          </svg>
        </span>
      );
    case "in-progress":
      return (
        <span
          className="relative flex h-9 w-9 items-center justify-center rounded-full"
          aria-hidden="true"
        >
          {/* Conic gradient spinning ring */}
          <span className="absolute inset-0 rounded-full conic-spinner opacity-80" />
          <span className="absolute inset-[3px] rounded-full bg-surface-base" />
          <span className="relative h-3 w-3 rounded-full bg-indigo-400 animate-pulse" />
        </span>
      );
    case "pending":
      return (
        <span
          className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.04] border border-white/[0.08]"
          aria-hidden="true"
        >
          <span className="block h-2.5 w-2.5 rounded-full bg-white/20" />
        </span>
      );
  }
}

function StageLabel({ name, status }: { name: string; status: StageStatus }) {
  const statusLabel =
    status === "complete"
      ? "Complete"
      : status === "in-progress"
        ? "In progress"
        : "Pending";

  const textColor =
    status === "complete"
      ? "text-emerald-400"
      : status === "in-progress"
        ? "text-indigo-300"
        : "text-white/30";

  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className={`text-xs font-semibold tracking-tight ${textColor}`}>{name}</span>
      <span className={`text-[10px] uppercase tracking-wider ${textColor} opacity-70`}>{statusLabel}</span>
    </div>
  );
}

function Connector({ status }: { status: "complete" | "pending" }) {
  return (
    <div
      className="hidden md:block flex-1 h-[2px] mx-3 rounded-full bg-white/[0.06] overflow-hidden min-w-[40px]"
      aria-hidden="true"
    >
      {status === "complete" && (
        <div className="h-full bg-emerald-500/50 connector-fill rounded-full" />
      )}
    </div>
  );
}

export function ProgressStepper({
  completedNodes,
  currentNode,
}: ProgressStepperProps) {
  const stageStatuses: { stage: StageDefinition; status: StageStatus }[] =
    STAGES.map((stage) => ({
      stage,
      status: deriveStageStatus(stage, completedNodes, currentNode),
    }));

  return (
    <div className="border-b border-white/[0.04] bg-surface-base/50 backdrop-blur-sm">
      <ol
        role="list"
        aria-label="Pipeline progress"
        className="flex flex-col md:flex-row items-center justify-center gap-4 md:gap-0 px-6 py-4"
      >
        {stageStatuses.map(({ stage, status }, index) => (
          <li
            key={stage.name}
            role="listitem"
            aria-label={`Stage: ${stage.name} - ${status === "in-progress" ? "In progress" : status === "complete" ? "Complete" : "Pending"}`}
            className="flex items-center"
          >
            <div className="flex flex-col items-center gap-2">
              <StageIcon status={status} />
              <StageLabel name={stage.name} status={status} />
            </div>
            {index < stageStatuses.length - 1 && (
              <Connector
                status={status === "complete" ? "complete" : "pending"}
              />
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
