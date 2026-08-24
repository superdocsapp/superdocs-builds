"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

import {
  IMPORT_STAGES,
  importStageStatus,
  importStatusLabel,
  type ImportFailure,
  type ImportPhase,
  type ImportStageStatus,
} from "../lib/import-state";
import { icons } from "@/lib/icons";
import { Button } from "./ui";
import { DocRelayAvatar } from "./brand";
import { TurnFrame } from "./conversation-events";
import { MotionPanel } from "./motion-panel";
import { useConversationWidthStyle } from "./workbench-split";

/**
 * Import takes the workbench's own geometry, so choosing a document, importing
 * it, and arriving in the workbench is one continuous movement rather than
 * three unrelated screens.
 */
export function ImportingDocument({
  documentName,
  phase,
  error,
  onRetry,
  onChooseAnother,
}: {
  documentName: string;
  phase: ImportPhase;
  error: ImportFailure | null;
  onRetry: () => void;
  onChooseAnother: () => void;
}) {
  const failed = phase === "FAILED" && error;
  const splitStyle = useConversationWidthStyle();
  const liveLabel = importStatusLabel(phase, documentName);

  return (
    <MotionPanel className="flex h-full min-h-0 flex-col">
      <div className="chrome-band px-4 lg:hidden">
        <p className="type-conversation-title min-w-0 truncate">
          {documentName}
        </p>
      </div>

      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {liveLabel}
      </div>

      <div
        style={splitStyle}
        className="workbench flex min-h-0 min-w-0 flex-1 overflow-hidden lg:m-[var(--workbench-inset)]"
      >
        <div
          className={cn(
            "conversation-pane flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-conversation",
            "lg:shrink-0",
          )}
        >
          <header className="chrome-band gap-3 px-5">
            <h1 className="type-conversation-title min-w-0 flex-1 truncate">{documentName}</h1>
            <span className={cn("pill shrink-0", failed ? "pill-warning" : "pill-neutral")}>
              <span
                className={cn(
                  "size-[6px] rounded-full",
                  failed ? "bg-warning" : "bg-muted-soft live-dot",
                )}
                aria-hidden="true"
              />
              {failed ? "Needs attention" : "Opening"}
            </span>
          </header>

          <div className="mx-auto min-h-0 w-full max-w-[576px] flex-1 overflow-y-auto px-5 py-7">
            {failed && error ? (
              <TurnFrame
                speaker="DocRelay"
                avatar={<DocRelayAvatar className="size-7" tone="soft" />}
                meta={
                  <span className="pill pill-warning">
                    <icons.warning className="size-3" strokeWidth={1.75} aria-hidden="true" />
                    Attention
                  </span>
                }
              >
                <p className="type-message font-medium">{error.title}</p>
                <p className="type-message mt-1 text-muted">{error.protection}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {error.retryable ? <Button onClick={onRetry}>Try again</Button> : null}
                  <Button variant="secondary" onClick={onChooseAnother}>
                    Choose another document
                  </Button>
                </div>
              </TurnFrame>
            ) : (
              <ol className="relative" aria-label="Import progress">
                {IMPORT_STAGES.map((stage, index) => {
                  const status = importStageStatus(stage.id, phase);
                  return (
                    <li key={stage.id} className="relative flex items-center gap-3 pb-3.5 last:pb-0">
                      {index < IMPORT_STAGES.length - 1 ? (
                        <span
                          className={cn(
                            "absolute top-[18px] bottom-0 left-[8.5px] w-px",
                            status === "complete" ? "bg-primary-line" : "bg-border-light",
                          )}
                          aria-hidden="true"
                        />
                      ) : null}
                      <ImportStageMark status={status} />
                      <span
                        className={cn(
                          "text-[13.5px] leading-5",
                          status === "active" && "font-medium text-foreground",
                          status === "complete" && "text-muted",
                          status === "pending" && "text-muted-soft",
                        )}
                      >
                        {stage.label}
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>

          <div className="mx-auto w-full max-w-[576px] shrink-0 px-5 pt-2 pb-4">
            <div
              className="h-[52px] rounded-[14px] border border-border-light bg-surface"
              aria-hidden="true"
            />
          </div>
        </div>

        {/* Same seam the resize gutter draws, so arriving in the workbench is
            a content change rather than a layout change. */}
        <div className="split-handle pointer-events-none" aria-hidden="true" />

        <div className="hidden min-h-0 min-w-0 flex-1 bg-canvas lg:flex">
          <DocumentPageSkeleton />
        </div>
      </div>
    </MotionPanel>
  );
}

function ImportStageMark({ status }: { status: ImportStageStatus }) {
  if (status === "complete") {
    return (
      <span
        className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-primary-line bg-accent-soft text-primary"
        aria-hidden="true"
      >
        <icons.check className="size-2.5" strokeWidth={2.75} />
      </span>
    );
  }
  if (status === "active") {
    return (
      <span className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-primary-line bg-surface">
        <span className="absolute inset-0 rounded-full bg-primary/12 live-dot" aria-hidden="true" />
        <Spinner className="size-2.5 text-primary" />
      </span>
    );
  }
  return (
    <span
      className="relative z-1 grid size-[18px] shrink-0 place-items-center rounded-full border border-border-light bg-surface"
      aria-hidden="true"
    >
      <span className="size-[6px] rounded-full bg-border" />
    </span>
  );
}

/**
 * The document pane while the source is still being read. It reproduces the
 * real pane's chrome and page geometry, so arriving in the workbench is a
 * content change rather than a layout change.
 */
function DocumentPageSkeleton() {
  return (
    <div className="flex min-h-0 w-full min-w-0 flex-col" aria-hidden="true">
      <div className="chrome-band gap-2.5 pr-2.5 pl-3.5">
        <Skeleton className="size-[18px] rounded-[5px]" />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-24" />
        <span className="flex-1" />
        <Skeleton className="size-[30px] rounded-[8px]" />
        <Skeleton className="h-[30px] w-28 rounded-[8px]" />
      </div>
      <div className="document-canvas flex min-h-0 flex-1 justify-center overflow-hidden px-6 pt-8 pb-14 lg:px-10 lg:pt-11 lg:pb-20">
        <div className="document-page">
          <Skeleton className="h-7 w-2/5" />
          <Skeleton className="mt-6 h-4 w-full" />
          <Skeleton className="mt-3 h-4 w-[94%]" />
          <Skeleton className="mt-3 h-4 w-[88%]" />
          <Skeleton className="mt-9 h-5 w-1/4" />
          <Skeleton className="mt-5 h-4 w-full" />
          <Skeleton className="mt-3 h-4 w-[91%]" />
          <Skeleton className="mt-3 h-4 w-[72%]" />
        </div>
      </div>
    </div>
  );
}
