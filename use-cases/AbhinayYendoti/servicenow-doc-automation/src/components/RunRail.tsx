import { useEffect, useRef } from "react";
import { Check, Loader2 } from "lucide-react";

import type { JobState, WorkflowState } from "../domain";

/**
 * The guided rail.
 *
 * Six fixed steps, so the shape of the run is visible before it starts, and
 * only the step you are on expands. The expansion says what the system is doing
 * right now and what it is waiting on — the difference between a progress bar
 * and a guide.
 */
export const steps: Array<{
  key: WorkflowState;
  label: string;
  helper: string;
  detail: string;
}> = [
  {
    key: "RECEIVED",
    label: "Change selected",
    helper: "ServiceNow record loaded",
    detail:
      "The record is read from the ServiceNow Table API and validated. An incomplete change is stopped here, before anything reaches SuperDocs."
  },
  {
    key: "UPLOADED",
    label: "Uploaded",
    helper: "Sent to SuperDocs",
    detail:
      "Fields are mapped to document sections verbatim and uploaded. SuperDocs splits the document into chunks it can edit individually."
  },
  {
    key: "EDITING",
    label: "SuperDocs editing",
    helper: "Drafting the rewrite",
    detail:
      "The model rewrites the document, holding every change for approval. Its progress appears in the activity feed as it works."
  },
  {
    key: "REVIEW_REQUIRED",
    label: "Decisions needed",
    helper: "Approve or reject each change",
    detail:
      "Each proposed chunk is checked against the ServiceNow record before you see it. Changes that rewrite an owned value cannot be approved."
  },
  {
    key: "APPROVED",
    label: "Approved",
    helper: "Document signed off",
    detail:
      "The finished document is re-verified and a human signs off. Export stays locked until both have happened."
  },
  {
    key: "EXPORTED",
    label: "Exported",
    helper: "Word file + ServiceNow note",
    detail:
      "SuperDocs renders the DOCX and the change record gets a work note naming the document and its checksum."
  }
];

export function RunRail({
  currentStep,
  job,
  sessionId
}: {
  currentStep: number;
  job: JobState | null;
  sessionId: string | null;
}) {
  const activeStep = useRef<HTMLDivElement | null>(null);

  /*
   * On a short window the rail scrolls, and the step that matters is the one
   * the run is on. Keep it in view as the run advances, so the rail leads
   * rather than having to be chased.
   */
  useEffect(() => {
    activeStep.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [currentStep]);

  return (
    <div className="progress-list" data-tour="rail">
      {steps.map((step, index) => {
        const done = index < currentStep;
        const active = index === currentStep;

        return (
          <div
            className={`progress-step ${index <= currentStep ? "active" : ""} ${active ? "current" : ""}`}
            key={step.key}
            ref={active ? activeStep : undefined}
          >
            <span className="progress-dot">
              {done ? <Check size={12} /> : active && job && !job.finished ? (
                <Loader2 className="spin" size={12} />
              ) : (
                index + 1
              )}
            </span>
            <div>
              <strong>{step.label}</strong>
              <span>{step.helper}</span>
              {active && <p className="progress-detail">{step.detail}</p>}
              {active && index === 2 && job?.progress != null && (
                <div className="progress-meter" aria-hidden="true">
                  <span style={{ width: `${Math.min(100, job.progress)}%` }} />
                </div>
              )}
            </div>
          </div>
        );
      })}

      {sessionId && (
        <p className="rail-session" title={sessionId}>
          session <code>{sessionId}</code>
        </p>
      )}
    </div>
  );
}
