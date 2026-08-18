"use client";

import type { ReactNode } from "react";
import { CornerDownLeft, Sparkles, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "./shell";

export type ConnectionState = "idle" | "connecting" | "connected" | "error";

/**
 * AI editing as a document command, not a chat. One line, docked under the
 * document it acts on.
 */
export function AiCommandBar({
  documentTitle,
  connectionState,
  connectionError,
  hasSession,
  instruction,
  busy,
  status,
  onInstructionChange,
  onSubmit,
  onConnect,
}: {
  documentTitle: string;
  connectionState: ConnectionState;
  connectionError: string | null;
  hasSession: boolean;
  instruction: string;
  busy: boolean;
  status: ReactNode;
  onInstructionChange: (value: string) => void;
  onSubmit: () => void;
  onConnect: () => void;
}) {
  return (
    <div className="shrink-0 border-t border-line bg-canvas/90 px-4 py-3 backdrop-blur-sm sm:px-6">
      <div className="mx-auto w-full max-w-[46rem] space-y-2">
        {status}

        {hasSession ? (
          <form
            className="flex items-center gap-2 rounded-[var(--radius-card)] border border-line-strong bg-surface py-1.5 pl-3 pr-1.5 shadow-[0_1px_2px_rgb(23_23_27/0.04)] transition-colors duration-150 focus-within:border-accent focus-within:ring-[3px] focus-within:ring-accent/15"
            onSubmit={(event) => {
              event.preventDefault();
              onSubmit();
            }}
          >
            <Sparkles className="size-4 shrink-0 text-accent" />
            <input
              type="text"
              value={instruction}
              disabled={busy}
              aria-label={`Ask AI to edit the ${documentTitle}`}
              placeholder={`Ask AI to edit the ${documentTitle}…`}
              onChange={(event) => onInstructionChange(event.target.value)}
              className="h-7 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint disabled:text-muted"
            />
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={busy || instruction.trim() === ""}
            >
              Propose edit
              <CornerDownLeft />
            </Button>
          </form>
        ) : (
          <ConnectRow
            connectionState={connectionState}
            connectionError={connectionError}
            busy={busy}
            onConnect={onConnect}
          />
        )}

        {hasSession && !status ? (
          <p className="px-1 text-xs text-faint">
            Language edits apply to this document only. Shared facts change
            through Policy facts, which updates every document that states them.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function ConnectRow({
  connectionState,
  connectionError,
  busy,
  onConnect,
}: {
  connectionState: ConnectionState;
  connectionError: string | null;
  busy: boolean;
  onConnect: () => void;
}) {
  if (connectionState === "connecting") {
    return (
      <div className="flex items-center gap-2.5 rounded-[var(--radius-card)] border border-line bg-surface px-3.5 py-2.5">
        <Spinner />
        <p className="text-[13px] text-muted" role="status">
          Uploading the four documents to SuperDocs…
        </p>
      </div>
    );
  }

  if (connectionState === "error") {
    return (
      <div className="flex items-center gap-2.5 rounded-[var(--radius-card)] border border-danger-line bg-danger-soft px-3.5 py-2.5">
        <TriangleAlert className="size-4 shrink-0 text-danger" />
        <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-danger" role="alert">
          {connectionError ?? "SuperDocs could not be reached."}
        </p>
        <Button variant="secondary" size="sm" onClick={onConnect} disabled={busy}>
          Try again
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2.5 rounded-[var(--radius-card)] border border-dashed border-line-strong bg-surface/60 px-3.5 py-2.5">
      <Sparkles className="size-4 shrink-0 text-faint" />
      <p className="min-w-0 flex-1 text-[13px] text-muted">
        Connect SuperDocs to edit these policies with AI.
      </p>
      <Button variant="primary" size="sm" onClick={onConnect} disabled={busy}>
        Connect SuperDocs
      </Button>
    </div>
  );
}
