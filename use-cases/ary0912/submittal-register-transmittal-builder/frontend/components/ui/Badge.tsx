import { cn } from "@/lib/utils";
import type { RegisterStatus, TechnicalStatus, FindingStatus } from "@/lib/api/types";
import { registerStatusLabel, technicalStatusLabel, findingStatusLabel } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "neutral" | "blue" | "amber" | "green" | "red" | "indigo" | "slate";
  className?: string;
}

export function Badge({ children, variant = "neutral", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium tracking-wide uppercase",
        {
          "bg-slate-100 text-slate-600": variant === "neutral" || variant === "slate",
          "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200": variant === "blue",
          "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200": variant === "amber",
          "bg-green-50 text-green-700 ring-1 ring-inset ring-green-200": variant === "green",
          "bg-red-50 text-red-700 ring-1 ring-inset ring-red-200": variant === "red",
          "bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200": variant === "indigo",
        },
        className,
      )}
    >
      {children}
    </span>
  );
}

// ============================================================
// Register Status Badge
// ============================================================

const registerVariant: Record<RegisterStatus, BadgeProps["variant"]> = {
  NOT_RECEIVED: "neutral",
  RECEIVED: "blue",
  UNDER_REVIEW: "amber",
  REVIEWED: "green",
  OVERDUE: "red",
};

export function RegisterStatusBadge({ status }: { status: RegisterStatus | string }) {
  const variant = registerVariant[status as RegisterStatus] ?? "neutral";
  return (
    <Badge variant={variant} aria-label={`Register status: ${registerStatusLabel(status as RegisterStatus)}`}>
      {registerStatusLabel(status as RegisterStatus)}
    </Badge>
  );
}

// ============================================================
// Technical Status Badge
// ============================================================

const techVariant: Record<string, BadgeProps["variant"]> = {
  PENDING: "neutral",
  PENDING_REVIEW: "amber",
  REVIEWED_DEVIATION: "red",
  REVIEWED_COMPLIANT: "green",
};

export function TechnicalStatusBadge({ status }: { status: TechnicalStatus | string }) {
  const variant = techVariant[status] ?? "neutral";
  return (
    <Badge variant={variant} aria-label={`Technical status: ${technicalStatusLabel(status)}`}>
      {technicalStatusLabel(status)}
    </Badge>
  );
}

// ============================================================
// Finding Status Badge
// ============================================================

const findingVariant: Record<string, BadgeProps["variant"]> = {
  PENDING_REVIEW: "amber",
  APPROVED: "green",
  REJECTED: "red",
  CLARIFICATION_REQUESTED: "indigo",
};

export function FindingStatusBadge({ status }: { status: FindingStatus | string }) {
  const variant = findingVariant[status] ?? "neutral";
  return (
    <Badge variant={variant} aria-label={`Finding status: ${findingStatusLabel(status)}`}>
      {findingStatusLabel(status)}
    </Badge>
  );
}

// ============================================================
// Comparison Result Badge
// ============================================================

export function ResultBadge({ result }: { result: string }) {
  return (
    <Badge
      variant={result === "DEVIATION" ? "red" : "green"}
      aria-label={`Comparison result: ${result === "DEVIATION" ? "Deviation" : "Match"}`}
    >
      {result === "DEVIATION" ? "Deviation" : "Match"}
    </Badge>
  );
}
