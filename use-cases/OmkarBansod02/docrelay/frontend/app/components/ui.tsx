import { Check } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { Button as PrimitiveButton } from "@/components/ui/button";
import { Skeleton as PrimitiveSkeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

import { StatusBanner } from "./feedback";

const variantMap = {
  primary: "default",
  secondary: "outline",
  ghost: "ghost",
  danger: "destructive",
} as const;

export function Button({
  variant = "primary",
  busy = false,
  className = "",
  children,
  disabled,
  asChild = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
  /** Render a link (or other element) with button geometry, so no screen
      needs to hand-roll a button-shaped anchor. */
  asChild?: boolean;
}) {
  return (
    <PrimitiveButton
      {...props}
      asChild={asChild}
      variant={variantMap[variant]}
      disabled={asChild ? undefined : disabled || busy}
      className={cn(className)}
    >
      {asChild ? (
        children
      ) : (
        <>
          {busy ? <Spinner className="size-4" /> : null}
          {children}
        </>
      )}
    </PrimitiveButton>
  );
}

export function StateMark({
  state = "idle",
  label,
}: {
  state?: "idle" | "current" | "complete" | "warning" | "info";
  label?: string;
}) {
  // Round marks, matching the progress rail: a run's state reads the same
  // wherever it appears — in a conversation, a table row or a page header.
  const styles = {
    idle: "border-border-light bg-surface text-transparent",
    current: "border-primary-line bg-surface text-primary",
    complete: "border-primary-line bg-accent-soft text-primary",
    warning: "border-warning/35 bg-warning-soft text-warning",
    info: "border-info/30 bg-info-soft text-info",
  };
  return (
    <span
      className={cn("grid size-[18px] shrink-0 place-items-center rounded-full border", styles[state])}
      aria-label={label}
    >
      {state === "complete" ? (
        <Check className="size-2.5" strokeWidth={2.75} />
      ) : state === "current" ? (
        <span className="size-[7px] rounded-full bg-primary" aria-hidden="true" />
      ) : state === "idle" ? (
        <span className="size-[6px] rounded-full bg-border" aria-hidden="true" />
      ) : (
        <span className="size-[6px] rounded-full bg-current" aria-hidden="true" />
      )}
    </span>
  );
}

export function InlineNotice({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "warning" | "info";
  children: ReactNode;
}) {
  if (tone === "neutral") {
    return (
      <div className="rounded-[var(--radius-card)] border border-border-light bg-surface px-4 py-3 text-[14px] leading-[1.6] text-ink shadow-[var(--shadow-subtle)]">
        {children}
      </div>
    );
  }
  return <StatusBanner tone={tone}>{children}</StatusBanner>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <PrimitiveSkeleton className={className} />;
}
