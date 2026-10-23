import { Check } from "lucide-react";
import { Link } from "react-router-dom";

import { cn } from "@/lib/utils";

export type StepperStep = {
  id: string;
  label: string;
  href: string;
  done?: boolean;
};

type ProgressStepperProps = {
  steps: StepperStep[];
  currentId: string;
};

export function ProgressStepper({ steps, currentId }: ProgressStepperProps) {
  const currentIndex = steps.findIndex((s) => s.id === currentId);

  return (
    <ol className="mb-8 grid gap-3 sm:grid-cols-3">
      {steps.map((step, index) => {
        const active = step.id === currentId;
        const complete = Boolean(step.done) || index < currentIndex;
        return (
          <li key={step.id}>
            <Link
              to={step.href}
              className={cn(
                "flex items-center gap-3 rounded-xl border px-3 py-3 transition",
                active && "border-primary bg-primary/5",
                complete && !active && "border-success/40 bg-success/5",
                !active && !complete && "border-border bg-card",
              )}
            >
              <span
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold",
                  active && "bg-primary text-primary-foreground",
                  complete && !active && "bg-success text-success-foreground",
                  !active && !complete && "bg-muted text-muted-foreground",
                )}
              >
                {complete && !active ? <Check className="h-4 w-4" /> : index + 1}
              </span>
              <span className="text-sm font-semibold">{step.label}</span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
