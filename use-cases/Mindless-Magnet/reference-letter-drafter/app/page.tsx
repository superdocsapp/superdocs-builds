"use client";

import { useState } from "react";
import { IntakeForm } from "@/components/IntakeForm";
import { ReviewPanel } from "@/components/ReviewPanel";
import { ExportButton } from "@/components/ExportButton";
import { useSessionStore } from "@/store/useSessionStore";
import type { Intake } from "@/lib/types";

export default function Home() {
  const { stage, sessionId, jobId, intake, error, setStage, setSessionId, setJobId, setIntake, setError, reset } =
    useSessionStore();
  const [starting, setStarting] = useState(false);

  async function handleIntakeSubmit(newIntake: Intake) {
    setStarting(true);
    setError(null);
    setIntake(newIntake);
    try {
      const sessionRes = await fetch("/api/session", { method: "POST" });
      if (!sessionRes.ok) throw new Error("Failed to start a document session");
      const { sessionId: newSessionId } = await sessionRes.json();
      setSessionId(newSessionId);

      const draftRes = await fetch("/api/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: newSessionId, intake: newIntake }),
      });
      if (!draftRes.ok) throw new Error("Failed to start drafting");
      const { job_id: newJobId } = await draftRes.json();
      setJobId(newJobId);
      setStage("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-10">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Reference Letter Drafter</h1>
        <p className="text-muted-foreground text-sm">
          Drafts reference and recommendation letters from a structured intake, in your own voice, calibrated to
          how strong you actually mean it. Built on SuperDocs.
        </p>
      </header>

      {error && <p className="text-destructive text-sm">{error}</p>}

      {stage === "intake" && (
        <div className="flex flex-col gap-4">
          {starting && <p className="text-muted-foreground text-sm">Starting your session…</p>}
          <IntakeForm onSubmit={handleIntakeSubmit} />
        </div>
      )}

      {stage === "review" && sessionId && jobId && (
        <ReviewPanel sessionId={sessionId} jobId={jobId} onCompleted={() => setStage("done")} />
      )}

      {stage === "done" && sessionId && intake && (
        <div className="flex flex-col gap-4">
          <p className="text-muted-foreground text-sm">Your letter is ready.</p>
          <ExportButton
            sessionId={sessionId}
            filename={`${intake.subjectName.replace(/\s+/g, "-").toLowerCase() || "reference-letter"}`}
          />
          <button
            type="button"
            className="text-muted-foreground w-fit text-sm underline"
            onClick={() => reset()}
          >
            Start another letter
          </button>
        </div>
      )}
    </div>
  );
}
