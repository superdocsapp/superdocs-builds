import { cn } from "@/lib/utils";

import { StateMark } from "./ui";

const steps = ["Source", "Instruction", "Review", "Safety check", "Write-back"] as const;
export type WorkflowStep = (typeof steps)[number];

export function WorkflowProgress({
  current,
  warning = false,
}: {
  current: WorkflowStep;
  warning?: boolean;
}) {
  const currentIndex = steps.indexOf(current);
  return (
    <nav
      aria-label="Document workflow"
      className="border-b border-border-light bg-surface-sunken px-6 sm:px-8 lg:px-10"
    >
      <div className="py-3.5 sm:hidden">
        <div className="flex items-center justify-between text-[13px]">
          <span className="flex items-center gap-2.5 font-medium text-ink">
            <StateMark state={warning ? "warning" : "current"} />
            {current}
          </span>
          <span className="type-caption tabular-nums">
            Step {currentIndex + 1} of {steps.length}
          </span>
        </div>
        <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-border-light" aria-hidden="true">
          <span
            className={cn(
              "block h-full rounded-full transition-[width] duration-[var(--motion-duration-lg)] ease-[var(--motion-ease)]",
              warning ? "bg-warning" : "bg-accent",
            )}
            style={{ width: `${((currentIndex + 1) / steps.length) * 100}%` }}
          />
        </div>
      </div>
      <ol className="hidden items-center py-4 sm:flex">
        {steps.map((step, index) => {
          const complete = index < currentIndex;
          const active = index === currentIndex;
          return (
            <li key={step} className="flex flex-1 items-center last:flex-none">
              <div
                className={cn(
                  "flex items-center gap-2.5 text-[13px] whitespace-nowrap",
                  active ? "font-medium text-ink" : "text-muted",
                )}
              >
                <StateMark
                  state={complete ? "complete" : active ? (warning ? "warning" : "current") : "idle"}
                />
                <span>{step}</span>
              </div>
              {index < steps.length - 1 ? (
                <span
                  className={cn(
                    "mx-3.5 h-px min-w-8 flex-1",
                    complete ? "bg-primary-line" : "bg-border-light",
                  )}
                  aria-hidden="true"
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
