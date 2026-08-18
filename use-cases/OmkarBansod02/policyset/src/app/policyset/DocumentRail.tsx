"use client";

import { POLICY_DOCUMENT_TYPES, type PolicyDocumentType } from "@/domain";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { DOCUMENT_ICONS, DOCUMENT_TITLES } from "./document-meta";

/** Real per-document state only — nothing here is invented. */
export type DocumentStatus = "idle" | "updated" | "review" | "working" | "issue";

const STATUS_LABELS: Record<Exclude<DocumentStatus, "idle">, string> = {
  updated: "Updated from SuperDocs",
  review: "Waiting for your review",
  working: "SuperDocs is working on this document",
  issue: "Consistency issue in this document",
};

export function DocumentRail({
  active,
  statuses,
  disabled,
  onSelect,
}: {
  active: PolicyDocumentType;
  statuses: Record<PolicyDocumentType, DocumentStatus>;
  disabled: boolean;
  onSelect: (documentType: PolicyDocumentType) => void;
}) {
  return (
    <nav aria-label="Policy documents" className="flex h-full flex-col">
      <p className="px-5 pb-2 pt-5 text-[11px] font-semibold uppercase tracking-[0.09em] text-faint">
        Policy set
      </p>

      <ul className="space-y-0.5 px-3">
        {POLICY_DOCUMENT_TYPES.map((documentType) => {
          const Icon = DOCUMENT_ICONS[documentType];
          const isActive = documentType === active;
          const status = statuses[documentType];

          return (
            <li key={documentType}>
              <button
                type="button"
                aria-current={isActive ? "page" : undefined}
                disabled={disabled}
                onClick={() => onSelect(documentType)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-2 text-left text-[13px] transition-colors duration-150",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                  isActive
                    ? "bg-surface font-medium text-ink shadow-[0_1px_2px_rgb(23_23_27/0.05)] ring-1 ring-line"
                    : "text-ink-soft hover:bg-surface/70 hover:text-ink",
                )}
              >
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    isActive ? "text-accent" : "text-faint",
                  )}
                />
                <span className="min-w-0 flex-1 truncate">
                  {DOCUMENT_TITLES[documentType]}
                </span>
                <StatusDot status={status} />
              </button>
            </li>
          );
        })}
      </ul>

      <p className="mt-auto px-5 pb-5 pt-8 text-xs leading-relaxed text-faint">
        One canonical profile behind four documents. Shared facts stay
        synchronized across the set.
      </p>
    </nav>
  );
}

function StatusDot({ status }: { status: DocumentStatus }) {
  if (status === "idle") {
    return null;
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            status === "updated" && "bg-ok",
            status === "review" && "bg-warn",
            status === "working" && "animate-pulse bg-accent",
            status === "issue" && "bg-danger",
          )}
        >
          <span className="sr-only">{STATUS_LABELS[status]}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="right">{STATUS_LABELS[status]}</TooltipContent>
    </Tooltip>
  );
}
