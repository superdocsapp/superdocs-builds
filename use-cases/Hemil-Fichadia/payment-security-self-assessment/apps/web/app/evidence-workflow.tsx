"use client";

import {
  EVIDENCE_CATEGORIES,
  EVIDENCE_STATUSES,
  groupEvidenceFacts,
  syntheticFintechEvidence,
  type EvidenceFact,
} from "@payment-security-self-assessment/evidence";
import { useState } from "react";
import { GenerateAssessment } from "./generate-assessment";

interface EvidenceApiResponse {
  files?: Array<{ id: string; name: string }>;
  facts?: EvidenceFact[];
  error?: string;
}

export function EvidenceWorkflow() {
  const [files, setFiles] = useState<File[]>([]);
  const [processedFiles, setProcessedFiles] = useState<string[]>([]);
  const [facts, setFacts] = useState<EvidenceFact[]>([]);
  const [state, setState] = useState<"idle" | "processing" | "error">("idle");
  const [error, setError] = useState("");
  const grouped = groupEvidenceFacts(facts);

  async function processEvidence() {
    if (files.length === 0 || state === "processing") return;

    setState("processing");
    setError("");
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    try {
      const response = await fetch("/api/evidence", { method: "POST", body: formData });
      const payload = (await response.json()) as EvidenceApiResponse;
      if (!response.ok || !payload.facts || !payload.files) {
        throw new Error(payload.error || "Unable to process evidence files.");
      }
      setFacts(payload.facts);
      setProcessedFiles(payload.files.map((file) => file.name));
      setState("idle");
    } catch (processingError) {
      setError(processingError instanceof Error ? processingError.message : "Unable to process evidence files.");
      setState("error");
    }
  }

  function useDemoEvidence() {
    setFiles([]);
    setProcessedFiles(["Meridian Payments synthetic corpus (demo)"]);
    setFacts(syntheticFintechEvidence);
    setError("");
    setState("idle");
  }

  return (
    <>
      <div className="workspace">
        <section className="panel" aria-labelledby="evidence-heading">
          <div className="panel-heading">
            <p className="section-label">Step 1</p>
            <h2 id="evidence-heading">Add evidence</h2>
          </div>
          <p className="panel-copy">Upload up to three plain-text security evidence files, 100 KB each.</p>
          <input
            type="file"
            accept=".txt,text/plain"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          {files.length > 0 && (
            <ul className="uploaded-files">
              {files.map((file) => <li key={`${file.name}-${file.size}`}>{file.name}</li>)}
            </ul>
          )}
          <div className="evidence-actions">
            <button type="button" onClick={processEvidence} disabled={files.length === 0 || state === "processing"}>
              {state === "processing" ? "Processing evidence…" : "Process evidence"}
            </button>
            <button type="button" className="secondary-button" onClick={useDemoEvidence}>Use fictional demo evidence</button>
          </div>
          {error && <p className="generation-error" role="alert">{error}</p>}
        </section>

        <GenerateAssessment facts={facts} />
      </div>

      <section className="demo-evidence" aria-labelledby="facts-heading">
        <div className="panel-heading">
          <p className="section-label">Step 2</p>
          <h2 id="facts-heading">Facts to generate from</h2>
        </div>
        <p className="panel-copy">
          {processedFiles.length > 0 ? `Processed: ${processedFiles.join(", ")}` : "Process uploads or choose the explicit fictional demo mode."}
        </p>
        {facts.length > 0 && <div className="evidence-categories">
          {Object.entries(EVIDENCE_CATEGORIES).map(([categoryId, label]) => (
            <section key={categoryId} className="evidence-category">
              <h3>{label}</h3>
              {EVIDENCE_STATUSES.map((status) => {
                const statusFacts = grouped[categoryId as keyof typeof grouped][status];
                return <div key={status} className="evidence-status-group">
                  <h4>{status}</h4>
                  {statusFacts.length ? <ul>{statusFacts.map((fact) => <li key={fact.id}>{fact.statement} <em>({fact.sourceDocumentName}, {fact.sourceReference})</em></li>)}</ul> : <p>No supplied facts.</p>}
                </div>;
              })}
            </section>
          ))}
        </div>}
      </section>
    </>
  );
}
