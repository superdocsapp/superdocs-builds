"use client";

import { useCallback, useEffect, useId, useRef, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import {
  canSubmitComposer,
  composerEnterIntent,
} from "../lib/conversation";
import { ICON_STROKE, icons } from "@/lib/icons";

export function ConversationComposer({
  value,
  busy,
  enabled = true,
  onChange,
  onSubmit,
}: {
  value: string;
  busy: boolean;
  enabled?: boolean;
  onChange: (value: string) => void;
  onSubmit: (instruction: string) => void;
}) {
  const fieldId = useId();
  const submittingRef = useRef(false);
  const blocked = busy || !enabled;
  const canSubmit = canSubmitComposer(value, blocked);

  const submit = useCallback(() => {
    if (!canSubmitComposer(value, busy || !enabled) || submittingRef.current) return;
    submittingRef.current = true;
    onSubmit(value.trim());
  }, [busy, enabled, onSubmit, value]);

  useEffect(() => {
    if (!busy) submittingRef.current = false;
  }, [busy]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const intent = composerEnterIntent(event);
    if (intent !== "submit") return;
    event.preventDefault();
    submit();
  };

  return (
    // One control, sized to the message rather than to a box: the field starts
    // a single line tall, grows with the instruction, and the only chrome on it
    // is the send key. The keyboard hint lives on that key, not under the form.
    <form
      className="mx-auto w-full max-w-[576px] shrink-0 bg-conversation px-5 pt-2 pb-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div
        className={cn(
          "relative rounded-[14px] border",
          "transition-[border-color,box-shadow,background-color] duration-[var(--motion-duration)] ease-[var(--motion-ease)]",
          "focus-within:border-ring focus-within:bg-surface focus-within:ring-3 focus-within:ring-ring/18",
          blocked
            ? "border-border-light bg-surface-sunken shadow-none"
            : "border-border bg-surface shadow-[var(--shadow-subtle)] hover:border-muted-soft/45",
        )}
      >
        <label htmlFor={fieldId} className="sr-only">
          Document change instruction
        </label>
        <Textarea
          id={fieldId}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask a question or request a change…"
          disabled={blocked}
          rows={1}
          aria-busy={busy}
          aria-describedby={`${fieldId}-hint`}
          className={cn(
            "max-h-[168px] min-h-[52px] w-full resize-none overflow-y-auto border-0 bg-transparent",
            "py-[14px] pr-[52px] pl-4 text-[14.5px] leading-[1.6] shadow-none placeholder:text-muted-soft",
            "focus-visible:border-transparent focus-visible:ring-0",
            "disabled:bg-transparent disabled:opacity-70",
          )}
        />
        <p id={`${fieldId}-hint`} className="sr-only">
          Press Enter to send, Shift plus Enter for a new line.
        </p>
        <Button
          type="submit"
          size="icon-sm"
          disabled={!canSubmit}
          title="Send · Enter"
          aria-label={busy ? "Sending instruction" : "Send instruction"}
          className="absolute right-[9px] bottom-[9px] size-[32px] rounded-[10px]"
        >
          {busy ? (
            <icons.refresh className="size-3.5 animate-spin" strokeWidth={ICON_STROKE} />
          ) : (
            <icons.send className="size-3.5" strokeWidth={2.25} />
          )}
        </Button>
      </div>
    </form>
  );
}
