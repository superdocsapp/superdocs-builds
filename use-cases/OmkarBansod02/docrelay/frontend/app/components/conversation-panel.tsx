"use client";

import { Children, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import type { UserInstructionTurn } from "../lib/conversation";
import { UserAvatar } from "./brand";
import { ConversationComposer } from "./conversation-composer";
import {
  DocRelayEvent,
  PersistedRunEvent,
  TurnFrame,
  VerifiedWriteEvent,
} from "./conversation-events";

export function ConversationPanel({
  title,
  stateLabel,
  turns,
  draft,
  busy,
  live = false,
  composerEnabled,
  onDraftChange,
  onSubmit,
  onRetry,
  children,
}: {
  title: string;
  stateLabel?: string;
  turns: UserInstructionTurn[];
  draft: string;
  busy: boolean;
  /** True only while the workflow is actually waiting on asynchronous work. */
  live?: boolean;
  composerEnabled: boolean;
  onDraftChange: (value: string) => void;
  onSubmit: (instruction: string) => void;
  onRetry: (turn: UserInstructionTurn) => void;
  children?: ReactNode;
}) {
  // `children` is an array of conditional workflow events, so it is truthy even
  // when every one of them is null. Counting the rendered nodes is what tells
  // us whether the thread actually holds anything yet.
  const empty = turns.length === 0 && Children.toArray(children).length === 0;

  return (
    // The surrounding pane owns the separation, so this panel never draws its
    // own outer divider.
    <section
      className="flex h-full min-h-0 min-w-0 flex-col overflow-x-hidden bg-conversation"
      aria-label="Document conversation"
    >
      {/* Same band as the document header: one strip of chrome runs across the
          whole workbench. The thread's state lives here and nowhere else. */}
      <header className="chrome-band gap-3 px-5">
        <h2 className="type-conversation-title min-w-0 flex-1 truncate">{title}</h2>
        {stateLabel ? <StateHint label={stateLabel} live={live} /> : null}
      </header>

      <ScrollArea className="scrollbar-inset min-h-0 min-w-0 flex-1">
        {/* Widening the pane adds breathing room around the thread rather than
            stretching every line to the edges. */}
        <div className="mx-auto flex min-h-full w-full max-w-[576px] min-w-0 flex-col px-5 pt-7 pb-6">
          {empty ? (
            <EmptyConversation onUseExample={composerEnabled ? onDraftChange : undefined} />
          ) : (
            // Looser between exchanges than inside one, so an instruction and
            // the answer to it read as a single unit.
            <ol className="flex min-w-0 flex-col gap-9" aria-label="Conversation">
              {turns.map((turn) => {
                // Reconstructed turns carry a persisted event; the active run does not.
                const historical = turn.persistedEvent !== undefined;
                return (
                  <li key={turn.id} className="min-w-0 space-y-5">
                    <UserTurn
                      turn={turn}
                      historical={historical}
                      onRetry={onRetry}
                      busy={busy}
                    />
                    {turn.persistedEvent ? (
                      <PersistedRunEvent event={turn.persistedEvent} />
                    ) : null}
                    {turn.verifiedWrite ? (
                      <VerifiedWriteEvent evidence={turn.verifiedWrite} />
                    ) : null}
                  </li>
                );
              })}
            </ol>
          )}
          {/* Consecutive workflow events are separated on the same rhythm as
              exchanges, so a long run reads as a sequence rather than a wall. */}
          {empty ? null : (
            <div className={cn("flex min-w-0 flex-col gap-8", turns.length > 0 ? "mt-9" : "")}>
              {children}
            </div>
          )}
        </div>
      </ScrollArea>

      <ConversationComposer
        value={draft}
        busy={busy}
        enabled={composerEnabled}
        onChange={onDraftChange}
        onSubmit={onSubmit}
      />
    </section>
  );
}

/** The one state chip in the conversation header, in the shared pill geometry. */
function StateHint({ label, live = false }: { label: string; live?: boolean }) {
  const attention = label === "Needs attention" || label === "Conflict";
  const positive = label === "Active" || label === "Verified" || label === "Ready";
  // The dot breathes only while something is genuinely pending, so a resting
  // "Active" thread is visibly still and a busy one is visibly not.
  const working = live || label === "Loading" || label === "Writing";
  return (
    <span
      className={cn(
        "pill shrink-0",
        attention ? "pill-warning" : positive ? "pill-accent" : "pill-neutral",
      )}
    >
      <span
        className={cn(
          "size-[6px] rounded-full",
          attention ? "bg-warning" : positive ? "bg-primary" : "bg-muted-soft",
          working ? "live-dot" : "",
        )}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

const EXAMPLE_INSTRUCTIONS = [
  'Change "30 days" to "45 days"',
  "Rename a heading",
  "Update a sentence",
] as const;

/**
 * Compact contextual empty state.
 *
 * It occupies the same turn frame as any other DocRelay message, so the pane
 * reads as a thread that has not started rather than as an onboarding screen.
 * It is rendered only while the thread holds no turns and no workflow event,
 * and disappears the moment either exists.
 */
function EmptyConversation({ onUseExample }: { onUseExample?: (value: string) => void }) {
  return (
    <DocRelayEvent title="Ready for an edit">
      <p className="type-message text-muted">
        Ask for a targeted change to this document. You&rsquo;ll review proposed edits before
        anything is written back.
      </p>
      <ul className="mt-3.5 flex min-w-0 flex-wrap gap-1.5" aria-label="Example instructions">
        {EXAMPLE_INSTRUCTIONS.map((example) => (
          <li key={example} className="min-w-0">
            {onUseExample ? (
              <button
                type="button"
                onClick={() => onUseExample(example)}
                className={cn(
                  "max-w-full truncate rounded-[7px] border border-border-light bg-surface px-2.5 py-1",
                  "text-[12.25px] leading-4 text-muted",
                  "transition-colors duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
                  "hover:border-border hover:text-foreground",
                )}
              >
                {example}
              </button>
            ) : (
              <span className="block max-w-full truncate rounded-[7px] border border-border-light bg-surface px-2.5 py-1 text-[12.25px] leading-4 text-muted">
                {example}
              </span>
            )}
          </li>
        ))}
      </ul>
    </DocRelayEvent>
  );
}

function UserTurn({
  turn,
  historical,
  onRetry,
  busy,
}: {
  turn: UserInstructionTurn;
  historical: boolean;
  onRetry: (turn: UserInstructionTurn) => void;
  busy: boolean;
}) {
  return (
    <TurnFrame
      label="You"
      speaker="You"
      avatar={<UserAvatar className="size-7" tone={historical ? "soft" : "solid"} />}
      meta={
        turn.status === "pending" ? (
          <span className="pill pill-neutral shrink-0">Sending…</span>
        ) : undefined
      }
    >
      {/* What you said rests on a quiet plate of its own against the tinted
          pane, at the same reading size as DocRelay's reply. It carries no
          elevation, so a semantic event card still outranks it. */}
      <div
        className={cn(
          "type-message min-w-0 rounded-[var(--radius-card)] border px-3.5 py-2.5",
          turn.status === "failed"
            ? "border-destructive/25 bg-error-soft py-3"
            : "border-border-light bg-surface",
        )}
      >
        <p className="break-words whitespace-pre-wrap">{turn.text}</p>
        {turn.status === "failed" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-destructive/15 pt-3">
            <p className="text-[13px] leading-5 text-destructive">
              {turn.error ?? "The instruction was not sent."}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onRetry(turn)}
            >
              Retry
            </Button>
          </div>
        ) : null}
      </div>
    </TurnFrame>
  );
}
