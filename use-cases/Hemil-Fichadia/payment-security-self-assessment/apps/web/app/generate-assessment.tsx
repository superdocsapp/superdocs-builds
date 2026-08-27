"use client";

import { useState } from "react";
import type { EvidenceFact } from "@payment-security-self-assessment/evidence";

type GenerationState = "idle" | "generating" | "complete" | "error";

interface AssessmentApiResponse {
  draftHtml?: string;
  error?: string;
}

export function GenerateAssessment({ facts }: { facts: EvidenceFact[] }) {
  const [state, setState] = useState<GenerationState>("idle");
  const [draftHtml, setDraftHtml] = useState("");
  const [error, setError] = useState("");

  async function handleGenerate() {
    if (state === "generating") {
      return;
    }

    setState("generating");
    setError("");

    try {
      const response = await fetch("/api/assessment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ facts }),
      });
      const payload = (await response.json()) as AssessmentApiResponse;

      if (!response.ok || typeof payload.draftHtml !== "string") {
        throw new Error(payload.error || "Unable to generate the assessment draft.");
      }

      setDraftHtml(payload.draftHtml);
      setState("complete");
    } catch (generationError) {
      setError(
        generationError instanceof Error
          ? generationError.message
          : "Unable to generate the assessment draft.",
      );
      setState("error");
    }
  }

  return (
    <>
      <section className="panel generate-panel" aria-labelledby="generate-heading">
        <div className="panel-heading">
          <p className="section-label">Step 3</p>
          <h2 id="generate-heading">Generate</h2>
        </div>
        <p className="panel-copy">
          Generate a draft from the currently inspected evidence facts. The
          draft is not a certification or final assessment.
        </p>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={state === "generating" || facts.length === 0}
          aria-describedby="generate-note"
        >
          {state === "generating" ? "Generating assessment…" : "Generate Assessment"}
        </button>
        <p id="generate-note" className="helper-text" role="status">
          {state === "generating"
            ? "SuperDocs is preparing the draft. This may take up to one minute."
            : facts.length > 0
              ? "Uses the inspected evidence facts through a server-side request."
              : "Process plain-text evidence before generating an assessment."}
        </p>
      </section>

      <section className="panel assessment-panel" aria-labelledby="assessment-heading">
        <div className="panel-heading">
          <p className="section-label">Step 4</p>
          <h2 id="assessment-heading">Assessment</h2>
        </div>
        {state === "complete" ? (
          <iframe
            className="generated-draft"
            title="Generated assessment draft"
            sandbox=""
            srcDoc={draftHtml}
          />
        ) : state === "error" ? (
          <p className="generation-error" role="alert">
            {error}
          </p>
        ) : (
          <div className="placeholder assessment-placeholder">
            <p>Your generated assessment will appear here.</p>
            <span>
              It will make the evidence behind implemented, planned, and
              unsupported claims easy to review.
            </span>
          </div>
        )}
      </section>
    </>
  );
}
