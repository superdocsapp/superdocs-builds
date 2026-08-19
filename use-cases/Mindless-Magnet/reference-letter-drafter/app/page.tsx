"use client";

import { useEffect, useState } from "react";
import { IntakeForm } from "@/components/IntakeForm";
import { ReviewPanel } from "@/components/ReviewPanel";
import { ExportButton } from "@/components/ExportButton";
import { Button } from "@/components/ui/button";
import { useSessionStore } from "@/store/useSessionStore";
import type { Intake, UsageStatus } from "@/lib/types";

export default function Home() {
  const { stage, sessionId, jobId, intake, error, setStage, setSession, setIntake, setError, reset } =
    useSessionStore();
  const [starting, setStarting] = useState(false);
  const [usage, setUsage] = useState<UsageStatus | null>(null);

  // Shown before anything is spent. A free tier that runs out halfway through
  // is a bad surprise, and the number is only useful in advance.
  useEffect(() => {
    fetch("/api/usage")
      .then((res) => (res.ok ? res.json() : null))
      .then(setUsage)
      .catch(() => setUsage(null));
  }, []);

  async function handleIntakeSubmit(newIntake: Intake) {
    setStarting(true);
    setError(null);
    setIntake(newIntake);

    try {
      const sessionRes = await fetch("/api/session", { method: "POST" });
      const sessionBody = await sessionRes.json();
      if (!sessionRes.ok) throw new Error(sessionBody.fix ?? "Could not start a document session.");

      const draftRes = await fetch("/api/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: sessionBody.sessionId, intake: newIntake }),
      });
      const draftBody = await draftRes.json();
      if (!draftRes.ok) {
        throw new Error(draftBody.fix ?? draftBody.cause ?? "Could not start the draft.");
      }

      setSession(sessionBody.sessionId, draftBody.job_id);
      setStage("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setStarting(false);
    }
  }

  const resumed = stage === "review" && Boolean(sessionId && jobId);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Reference Letter Drafter</h1>
        <p className="text-muted-foreground text-sm">
          Drafts reference and recommendation letters from a structured intake, in your own voice, and
          checks that the result reads as strongly as you actually meant it. A lukewarm reference should
          read as lukewarm. Built on SuperDocs.
        </p>
        {usage?.operationsRemaining !== undefined && (
          <p className={`text-xs ${usage.lowBudget ? "text-amber-600 dark:text-amber-500" : "text-muted-foreground"}`}>
            {usage.operationsRemaining} SuperDocs operations remaining
            {usage.lowBudget ? ". Each draft costs about one." : ""}
          </p>
        )}
      </header>

      {error && (
        <div className="border-destructive/40 rounded-md border p-3">
          <p className="text-destructive text-sm">{error}</p>
        </div>
      )}

      {stage === "intake" && (
        <div className="flex flex-col gap-4">
          {starting && (
            <p className="text-muted-foreground text-sm">Starting the session and sending the draft…</p>
          )}
          <IntakeForm onSubmit={handleIntakeSubmit} disabled={starting} />
        </div>
      )}

      {resumed && intake && sessionId && jobId && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-muted-foreground text-sm">
              Letter for {intake.subjectName}, declared {intake.strengthBand}.
            </p>
            <Button variant="ghost" size="sm" onClick={reset}>
              Discard and start over
            </Button>
          </div>
          <ReviewPanel
            sessionId={sessionId}
            jobId={jobId}
            intake={intake}
            onCompleted={() => setStage("done")}
          />
        </div>
      )}

      {stage === "done" && sessionId && intake && (
        <div className="flex flex-col gap-4">
          <p className="text-muted-foreground text-sm">
            Everything you approved has been written. Nothing you rejected was applied.
          </p>
          <ExportButton
            sessionId={sessionId}
            filename={intake.subjectName.replace(/\s+/g, "-").toLowerCase() || "reference-letter"}
          />
          <Button variant="ghost" size="sm" className="w-fit" onClick={reset}>
            Start another letter
          </Button>
        </div>
      )}
    </div>
  );
}
