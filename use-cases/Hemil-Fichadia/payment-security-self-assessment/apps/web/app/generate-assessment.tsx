"use client";

import { useState } from "react";
import type { EvidenceFact } from "@payment-security-self-assessment/evidence";

type WorkflowState = "idle" | "processing" | "awaitingApproval" | "approving" | "approved" | "exporting" | "error";
type ProposedChange = { change_id: string; operation: "edit" | "create" | "delete"; old_html?: string; new_html?: string };
type WorkflowResponse = { workflowId?: string; state?: string; proposedChanges?: ProposedChange[]; draftHtml?: string; error?: string };

export function GenerateAssessment({ facts }: { facts: EvidenceFact[] }) {
  const [state, setState] = useState<WorkflowState>("idle");
  const [workflowId, setWorkflowId] = useState("");
  const [changes, setChanges] = useState<ProposedChange[]>([]);
  const [draftHtml, setDraftHtml] = useState("");
  const [error, setError] = useState("");

  async function readJson(response: Response): Promise<WorkflowResponse> {
    return (await response.json()) as WorkflowResponse;
  }

  async function poll(id: string): Promise<void> {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1_000));
      const response = await fetch(`/api/assessment/${id}`, { cache: "no-store" });
      const payload = await readJson(response);
      if (!response.ok) throw new Error(payload.error || "Unable to retrieve assessment status.");
      if (payload.state === "AWAITING_APPROVAL") {
        setChanges(payload.proposedChanges ?? []);
        setState("awaitingApproval");
        return;
      }
      if (payload.state === "APPROVED") {
        setDraftHtml(payload.draftHtml ?? "");
        setState("approved");
        return;
      }
      if (payload.state === "FAILED") throw new Error(payload.error || "SuperDocs could not complete the assessment.");
    }
    throw new Error("Assessment processing is taking longer than expected. Please try again.");
  }

  async function handleGenerate() {
    if (facts.length === 0 || state === "processing") return;
    setState("processing"); setError(""); setChanges([]); setDraftHtml("");
    try {
      const response = await fetch("/api/assessment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facts }) });
      const payload = await readJson(response);
      if (!response.ok || !payload.workflowId) throw new Error(payload.error || "Unable to start assessment generation.");
      setWorkflowId(payload.workflowId);
      await poll(payload.workflowId);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to generate the assessment."); setState("error"); }
  }

  async function handleApprove() {
    if (!workflowId || state !== "awaitingApproval") return;
    setState("approving"); setError("");
    try {
      const response = await fetch(`/api/assessment/${workflowId}/approve`, { method: "POST" });
      const payload = await readJson(response);
      if (!response.ok) throw new Error(payload.error || "Unable to approve assessment changes.");
      await poll(workflowId);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to approve assessment changes."); setState("error"); }
  }

  async function handleExport() {
    if (!workflowId || state !== "approved") return;
    setState("exporting"); setError("");
    try {
      const response = await fetch(`/api/assessment/${workflowId}/export`);
      if (!response.ok) { const payload = await readJson(response); throw new Error(payload.error || "Unable to export the assessment."); }
      const link = document.createElement("a");
      link.href = URL.createObjectURL(await response.blob());
      link.download = "payment-security-self-assessment.docx";
      link.click();
      URL.revokeObjectURL(link.href);
      setState("approved");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to export the assessment."); setState("error"); }
  }

  const busy = state === "processing" || state === "approving" || state === "exporting";
  return <>
    <section className="panel generate-panel" aria-labelledby="generate-heading"><div className="panel-heading"><p className="section-label">Step 3</p><h2 id="generate-heading">Generate assessment</h2></div><p className="panel-copy">Upload a temporary assessment template to SuperDocs and request changes from the inspected evidence.</p><button type="button" onClick={handleGenerate} disabled={facts.length === 0 || busy}>{state === "processing" ? "Generating assessment…" : "Generate Assessment"}</button></section>
    <section className="panel assessment-panel" aria-labelledby="assessment-heading"><div className="panel-heading"><p className="section-label">Step 4</p><h2 id="assessment-heading">Review generated draft</h2></div>{state === "awaitingApproval" || state === "approving" ? <><p className="helper-text">Changes are proposed by SuperDocs and are awaiting human approval. They have not been finalized.</p>{changes.map((change) => <article key={change.change_id} className="placeholder"><p><strong>{change.operation}</strong></p>{change.old_html && <iframe className="generated-draft" title={`Current ${change.change_id}`} sandbox="" srcDoc={change.old_html} />}{change.new_html && <iframe className="generated-draft" title={`Proposed ${change.change_id}`} sandbox="" srcDoc={change.new_html} />}</article>)}</> : state === "approved" || state === "exporting" ? <iframe className="generated-draft" title="Approved assessment draft" sandbox="" srcDoc={draftHtml} /> : <div className="placeholder assessment-placeholder"><p>{state === "processing" ? "SuperDocs is preparing proposed changes…" : "Your proposed assessment changes will appear here."}</p></div>}</section>
    <section className="panel" aria-labelledby="approve-heading"><div className="panel-heading"><p className="section-label">Step 5</p><h2 id="approve-heading">Approve changes</h2></div><p className="panel-copy">Approval is an explicit server-side SuperDocs action.</p><button type="button" onClick={handleApprove} disabled={state !== "awaitingApproval"}>{state === "approving" ? "Approving changes…" : "Approve changes"}</button></section>
    <section className="panel" aria-labelledby="export-heading"><div className="panel-heading"><p className="section-label">Step 6</p><h2 id="export-heading">Export assessment</h2></div><p className="panel-copy">Export is available only after approval succeeds.</p><button type="button" onClick={handleExport} disabled={state !== "approved"}>{state === "exporting" ? "Exporting assessment…" : "Export assessment"}</button>{error && <p className="generation-error" role="alert">{error}</p>}</section>
  </>;
}
