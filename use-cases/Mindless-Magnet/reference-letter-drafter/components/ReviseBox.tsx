"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";

/**
 * A freeform message to SuperDocs on the same session, outside the per-change
 * approve/reject flow — "make the second paragraph shorter," "mention she led
 * the migration," things a structured form has no field for.
 *
 * This sends another chat turn, which produces a new job with its own
 * pending changes. Those flow through the same review cards already on this
 * page: a revision is not auto-applied any more than the first draft was.
 */
export function ReviseBox({
  sessionId,
  memoryKey,
  disabled,
  disabledReason,
  onRevised,
}: {
  sessionId: string;
  memoryKey: string;
  disabled?: boolean;
  disabledReason?: string;
  onRevised: (jobId: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    const trimmed = message.trim();
    if (!trimmed) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch("/api/revise", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, message: trimmed, memoryKey }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.fix ?? body.cause ?? "Could not send that request.");
      setMessage("");
      onRevised(body.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send that request.");
    } finally {
      setSending(false);
    }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Ask for a change</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Textarea
          placeholder='e.g. "Make the second paragraph shorter" or "Mention she led the Q3 migration"'
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={2}
          disabled={disabled || sending}
          maxLength={2000}
        />
        {disabled && disabledReason && <p className="text-muted-foreground text-xs">{disabledReason}</p>}
        {error && <p className="text-destructive text-sm">{error}</p>}
        <Button
          size="sm"
          className="w-fit"
          disabled={disabled || sending || !message.trim()}
          onClick={send}
        >
          {sending ? "Sending…" : "Send to SuperDocs"}
        </Button>
      </CardContent>
    </Card>
  );
}
