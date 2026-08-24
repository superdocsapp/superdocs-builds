"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import type { FrozenPreviewBlock, SourceRegistration } from "../lib/api";
import type { DocumentReviewMark } from "../lib/conversation";
import { googleDocsUrl, truncateRevision } from "../lib/conversation";
import { ICON_STROKE, icons } from "@/lib/icons";
import { GoogleDocsMark, GoogleDriveMark } from "./brand";
import { DocumentPreviewUnavailable, DocumentRenderer } from "./document-renderer";
import { MotionFade } from "./motion-panel";

export function DocumentPanel({
  source,
  blocks,
  revision,
  reviewMarks,
  onChangeSource,
}: {
  source: SourceRegistration;
  blocks: FrozenPreviewBlock[] | null;
  revision?: string;
  reviewMarks?: DocumentReviewMark[];
  onChangeSource: () => void;
}) {
  const currentRevision = revision ?? source.baseline.revision_id;
  const fileId = source.source.provider_file_id;
  const driveUrl = googleDocsUrl(fileId);
  const marked = (reviewMarks ?? []).length;

  return (
    <section
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-canvas"
      aria-label="Document"
    >
      {/* One row of quiet editor chrome, on the same band as the conversation
          header. It states only what the API actually proved — provider,
          frozen revision, read-only — and keeps all of it secondary to the
          page underneath. */}
      <header className="chrome-band gap-2 pr-2.5 pl-3.5">
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          <GoogleDocsMark className="size-[18px]" />
          <span className="hidden shrink-0 text-[12.75px] font-medium tracking-[-0.01em] text-muted sm:inline">
            Google Docs
          </span>
          <Divider className="hidden sm:block" />
          <RevisionMark revision={currentRevision} />
          <Divider className="hidden lg:block" />
          <span
            className="hidden shrink-0 items-center gap-1.5 text-[12.25px] leading-4 text-muted-soft lg:inline-flex"
            aria-hidden="true"
          >
            <icons.lock className="size-3 shrink-0" strokeWidth={ICON_STROKE} />
            Read-only
          </span>
          {/* Announced once at every width, however much of the row is shown. */}
          <span className="sr-only">Read-only view of the frozen revision</span>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {marked > 0 ? (
            <span className="pill pill-warning mr-1 shrink-0">
              {marked === 1 ? "1 span in review" : `${marked} spans in review`}
            </span>
          ) : null}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon-sm" asChild>
                <a href={driveUrl} target="_blank" rel="noreferrer">
                  <GoogleDriveMark className="size-[15px]" />
                  <span className="sr-only">Open in Google Drive</span>
                </a>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Open in Google Drive</TooltipContent>
          </Tooltip>
          <Button type="button" variant="outline" size="sm" onClick={onChangeSource}>
            Change source
          </Button>
        </div>
      </header>

      <ScrollArea className="scrollbar-inset min-h-0 min-w-0 flex-1">
        {/* The canvas is a container: the page's measure and margins respond to
            the pane, so both a narrow and a wide split look intentional. The
            page sits high on the canvas with room to scroll past its end. */}
        <div className="document-canvas flex min-h-full min-w-0 justify-center px-6 pt-8 pb-14 lg:px-10 lg:pt-11 lg:pb-20">
          {blocks ? (
            <MotionFade key={currentRevision} className="flex min-w-0 flex-1 justify-center">
              <DocumentRenderer
                title={source.source.name}
                blocks={blocks}
                reviewMarks={reviewMarks}
              />
            </MotionFade>
          ) : (
            <DocumentPreviewUnavailable />
          )}
        </div>
      </ScrollArea>
    </section>
  );
}

function Divider({ className }: { className?: string }) {
  return (
    <span
      className={cn("h-3 w-px shrink-0 bg-border", className)}
      aria-hidden="true"
    />
  );
}

function RevisionMark({ revision }: { revision: string }) {
  const [copied, setCopied] = useState(false);
  const short = truncateRevision(revision);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "group/revision -mx-1.5 inline-flex min-w-0 items-center gap-1 rounded-[6px] px-1.5 py-1",
            "text-[12.25px] whitespace-nowrap text-muted",
            "transition-colors duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
            "hover:bg-surface-muted hover:text-foreground",
          )}
          onClick={() => {
            void navigator.clipboard?.writeText(revision).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1200);
            });
          }}
        >
          <span className="truncate">
            Revision <span className="type-mono text-[11px]">{short}</span>
          </span>
          <icons.copy
            className="size-3 shrink-0 text-muted-soft opacity-0 transition-opacity duration-[var(--motion-duration)] group-hover/revision:opacity-100 group-focus-visible/revision:opacity-100"
            strokeWidth={ICON_STROKE}
            aria-hidden="true"
          />
          <span className="sr-only">{copied ? "Revision copied" : "Copy full revision"}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{copied ? "Copied" : revision}</TooltipContent>
    </Tooltip>
  );
}
