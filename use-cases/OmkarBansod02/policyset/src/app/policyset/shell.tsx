"use client";

import type { ReactNode } from "react";
import { CircleCheck, LoaderCircle, Scale, TriangleAlert } from "lucide-react";
import type { ValidationResult } from "@/domain";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * The single application chrome used by every PolicySet screen. Deliberately
 * short: the working surface below it is what matters.
 */
export function AppHeader({
  context,
  leading,
  children,
}: {
  context?: string;
  leading?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-chrome/90 backdrop-blur-sm">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-5">
        {leading}
        <Wordmark />
        {context ? (
          <>
            <Separator
              orientation="vertical"
              className="hidden h-4 sm:block"
            />
            <span className="hidden min-w-0 truncate text-[13px] text-muted sm:block">
              {context}
            </span>
          </>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">{children}</div>
      </div>
    </header>
  );
}

function Wordmark() {
  return (
    <span className="flex shrink-0 items-center gap-2">
      <span
        aria-hidden="true"
        className="grid size-6 place-items-center rounded-[7px] bg-ink text-white"
      >
        <Scale className="size-3.5" strokeWidth={2} />
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-ink">
        PolicySet
      </span>
    </span>
  );
}

/**
 * Consistency is the product's trust signal, so it stays visible — but quiet
 * while everything is fine. Only real validation state is rendered here.
 */
export function ConsistencyStatus({
  validation,
  reviewingCount = 0,
}: {
  validation: ValidationResult;
  reviewingCount?: number;
}) {
  if (reviewingCount > 0) {
    return (
      <StatusLine tone="warn" icon={<Pulse />}>
        Reviewing changes across {reviewingCount}{" "}
        {reviewingCount === 1 ? "policy" : "policies"}
      </StatusLine>
    );
  }

  if (validation.ok) {
    return (
      <StatusLine tone="ok" icon={<CircleCheck className="size-3.5" />}>
        All policies consistent
      </StatusLine>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="rounded-md focus-visible:outline-2"
          aria-label={`Policy consistency check failed: ${validation.issues.length} issues`}
        >
          <StatusLine tone="danger" icon={<TriangleAlert className="size-3.5" />}>
            Consistency check failed
          </StatusLine>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        <ul className="space-y-1">
          {validation.issues.map((issue) => (
            <li key={`${issue.code}:${issue.message}`}>{issue.message}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

function StatusLine({
  tone,
  icon,
  children,
}: {
  tone: "ok" | "warn" | "danger";
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <span
      role="status"
      className={cn(
        "flex items-center gap-1.5 whitespace-nowrap text-[13px] font-medium",
        tone === "ok" && "text-ok",
        tone === "warn" && "text-warn",
        tone === "danger" && "text-danger",
      )}
    >
      {icon}
      <span className="hidden md:inline">{children}</span>
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <LoaderCircle
      aria-hidden="true"
      className={cn("size-4 shrink-0 animate-spin text-muted", className)}
    />
  );
}

function Pulse() {
  return (
    <span aria-hidden="true" className="relative flex size-2.5 items-center justify-center">
      <span className="absolute inline-flex size-2.5 animate-ping rounded-full bg-warn/40" />
      <span className="relative inline-flex size-1.5 rounded-full bg-warn" />
    </span>
  );
}
