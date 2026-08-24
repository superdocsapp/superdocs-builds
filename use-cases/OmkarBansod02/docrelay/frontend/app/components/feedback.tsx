import type { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

import { ICON_STROKE, icons } from "@/lib/icons";

export function LoadingSpinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-muted" role="status" aria-live="polite">
      <Spinner className="size-4 text-primary" />
      <span className="type-caption">{label}</span>
    </div>
  );
}

export function DocumentRowSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="divide-y divide-border" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3 py-3">
          <Skeleton className="size-4 rounded" />
          <Skeleton className="h-4 w-48 max-w-[45%]" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon: Icon = icons.document,
  title,
  description,
  action,
}: {
  icon?: typeof icons.document;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-5 py-16 text-center">
      <span className="grid size-10 place-items-center rounded-[10px] border border-border-light bg-surface-elevated text-muted">
        <Icon className="size-[18px]" strokeWidth={ICON_STROKE} />
      </span>
      <h2 className="type-document-title mt-4">{title}</h2>
      <p className="type-body-muted mt-2">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function StatusBanner({
  tone,
  title,
  children,
}: {
  tone: "success" | "warning" | "error" | "info";
  title?: string;
  children: ReactNode;
}) {
  const Icon =
    tone === "success"
      ? icons.success
      : tone === "warning"
        ? icons.warning
        : tone === "info"
          ? icons.info
          : icons.error;
  const variant = tone === "error" ? "destructive" : tone;
  return (
    <Alert variant={variant}>
      <Icon className="size-4" strokeWidth={ICON_STROKE} />
      {title ? <AlertTitle>{title}</AlertTitle> : null}
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

export function FeedbackAction({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <Button type="button" variant="outline" onClick={onClick}>
      {children}
    </Button>
  );
}
