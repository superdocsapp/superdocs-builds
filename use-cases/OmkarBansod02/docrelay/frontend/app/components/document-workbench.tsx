"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

import type { FrozenDocumentPreview, SourceRegistration } from "../lib/api";
import type { DocumentReviewMark, UserInstructionTurn } from "../lib/conversation";
import { frozenPreviewBlocks } from "../lib/conversation";
import { ICON_STROKE, icons } from "@/lib/icons";
import { ConversationPanel } from "./conversation-panel";
import { DocumentPanel } from "./document-panel";
import { MotionPanel } from "./motion-panel";
import { useConversationSplit } from "./workbench-split";

export function DocumentWorkbench({
  source,
  turns,
  draft,
  busy,
  live,
  composerEnabled,
  stateLabel,
  onDraftChange,
  onSubmit,
  onRetry,
  onChangeSource,
  reviewMarks,
  documentPreview,
  documentRevision,
  children,
}: {
  source: SourceRegistration;
  turns: UserInstructionTurn[];
  draft: string;
  busy: boolean;
  live?: boolean;
  composerEnabled: boolean;
  stateLabel?: string;
  onDraftChange: (value: string) => void;
  onSubmit: (instruction: string) => void;
  onRetry: (turn: UserInstructionTurn) => void;
  onChangeSource: () => void;
  reviewMarks?: DocumentReviewMark[];
  documentPreview?: FrozenDocumentPreview;
  documentRevision?: string;
  children?: ReactNode;
}) {
  const blocks = frozenPreviewBlocks(documentPreview ?? source.preview);
  const [documentOpen, setDocumentOpen] = useState(false);
  const { containerRef, containerStyle, handleProps } = useConversationSplit();

  return (
    <MotionPanel className="flex h-full min-h-0 flex-col">
      <div className="chrome-band justify-between gap-3 px-4 lg:hidden">
        <p className="type-conversation-title min-w-0 truncate">
          {source.source.name}
        </p>
        <Sheet open={documentOpen} onOpenChange={setDocumentOpen}>
          <SheetTrigger asChild>
            <Button type="button" variant="outline" size="sm">
              <icons.document data-icon="inline-start" strokeWidth={ICON_STROKE} />
              View document
            </Button>
          </SheetTrigger>
          <SheetContent
            side="right"
            className="w-[min(100%,30rem)] p-0 sm:max-w-[30rem]"
          >
            <SheetTitle className="sr-only">Document</SheetTitle>
            <DocumentPanel
              source={source}
              blocks={blocks}
              revision={documentRevision}
              reviewMarks={reviewMarks}
              onChangeSource={onChangeSource}
            />
          </SheetContent>
        </Sheet>
      </div>

      {/* One workspace holding two tools. The frame owns the outer border and
          radius; inside it the conversation and the document are flush regions
          separated only by the seam in the resize gutter, so the workbench
          never reads as two cards floating on a board. */}
      <div
        ref={containerRef}
        style={containerStyle}
        className="workbench flex min-h-0 min-w-0 flex-1 overflow-hidden lg:m-[var(--workbench-inset)]"
      >
        <div
          className={cn(
            "conversation-pane flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-conversation",
            "lg:shrink-0",
          )}
        >
          <ConversationPanel
            title={source.source.name}
            stateLabel={stateLabel}
            turns={turns}
            draft={draft}
            busy={busy}
            live={live}
            composerEnabled={composerEnabled}
            onDraftChange={onDraftChange}
            onSubmit={onSubmit}
            onRetry={onRetry}
          >
            {children}
          </ConversationPanel>
        </div>

        <div {...handleProps} />

        <div className="hidden min-h-0 min-w-0 flex-1 lg:flex">
          <DocumentPanel
            source={source}
            blocks={blocks}
            revision={documentRevision}
            reviewMarks={reviewMarks}
            onChangeSource={onChangeSource}
          />
        </div>
      </div>
    </MotionPanel>
  );
}
