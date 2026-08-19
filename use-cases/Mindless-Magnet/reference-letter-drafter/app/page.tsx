"use client";

import { useEffect, useState } from "react";
import { IntakeForm } from "@/components/IntakeForm";
import { ReviewPanel } from "@/components/ReviewPanel";
import { HistoryList } from "@/components/HistoryList";
import { Button } from "@/components/ui/button";
import { useSessionStore } from "@/store/useSessionStore";
import { upsertHistory } from "@/lib/history";
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
      upsertHistory({
        sessionId: sessionBody.sessionId,
        jobId: draftBody.job_id,
        subjectName: newIntake.subjectName,
        writerName: newIntake.writerName,
        strengthBand: newIntake.strengthBand,
        createdAt: new Date().toISOString(),
        status: "reviewing",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setStarting(false);
    }
  }

  function handleResumeFromHistory(historySessionId: string, historyJobId: string, historyIntake: Intake) {
    setIntake(historyIntake);
    setSession(historySessionId, historyJobId);
    setStage("review");
  }

  const resumed = stage === "review" && Boolean(sessionId && jobId);

  return (
    <div className="from-background to-muted/40 min-h-full bg-gradient-to-b">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10 sm:py-14">
        <header className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-primary text-xs font-semibold tracking-widest uppercase">
                Built on SuperDocs
              </span>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Reference Letter Drafter</h1>
              <p className="text-muted-foreground max-w-xl text-sm leading-relaxed">
                Drafts reference and recommendation letters from a structured intake, in your own voice,
                and checks that the result reads as strongly as you actually meant it. A lukewarm
                reference should read as lukewarm.
              </p>
            </div>
            {stage !== "history" && (
              <Button variant="outline" size="sm" className="shrink-0" onClick={() => setStage("history")}>
                Past letters
              </Button>
            )}
          </div>
          {usage?.operationsRemaining !== undefined && (
            <p
              className={`w-fit rounded-full border px-3 py-1 text-xs ${
                usage.lowBudget
                  ? "border-amber-600/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
                  : "border-border bg-muted/50 text-muted-foreground"
              }`}
            >
              {usage.operationsRemaining} SuperDocs operations remaining
              {usage.lowBudget ? " — each draft costs about one." : ""}
            </p>
          )}
        </header>

        {error && (
          <div className="border-destructive/40 bg-destructive/5 rounded-lg border p-4">
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
            <div className="bg-card flex items-center justify-between gap-3 rounded-lg border px-4 py-3">
              <p className="text-sm">
                Letter for <span className="font-medium">{intake.subjectName}</span>, declared{" "}
                <span className="font-medium">{intake.strengthBand}</span>.
              </p>
              <Button variant="ghost" size="sm" onClick={reset}>
                Discard and start over
              </Button>
            </div>
            <ReviewPanel
              key={jobId}
              sessionId={sessionId}
              jobId={jobId}
              intake={intake}
              onCompleted={() =>
                upsertHistory({
                  sessionId,
                  jobId,
                  subjectName: intake.subjectName,
                  writerName: intake.writerName,
                  strengthBand: intake.strengthBand,
                  createdAt: new Date().toISOString(),
                  status: "done",
                })
              }
              onRevised={(newJobId) => {
                setSession(sessionId, newJobId);
                upsertHistory({
                  sessionId,
                  jobId: newJobId,
                  subjectName: intake.subjectName,
                  writerName: intake.writerName,
                  strengthBand: intake.strengthBand,
                  createdAt: new Date().toISOString(),
                  status: "reviewing",
                });
              }}
            />
          </div>
        )}

        {stage === "history" && (
          <HistoryList
            onResume={handleResumeFromHistory}
            onBack={() => setStage(sessionId && jobId ? "review" : "intake")}
          />
        )}
      </div>
    </div>
  );
}
