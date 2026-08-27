import { getAssessmentWorkflow, updateAssessmentWorkflow } from "@/lib/server/assessment-workflow";
import { AssessmentGenerationError, getAssessmentJob, validateGeneratedDraft } from "@/lib/server/superdocs";

export const runtime = "nodejs";

export async function GET(_: Request, { params }: { params: Promise<{ workflowId: string }> }) {
  const { workflowId } = await params;
  const workflow = getAssessmentWorkflow(workflowId);
  if (!workflow) return Response.json({ error: "Assessment workflow was not found. Start generation again.", code: "WORKFLOW_NOT_FOUND" }, { status: 404 });

  try {
    const job = await getAssessmentJob(workflow.jobId);
    if (job.status === "awaiting_approval") {
      updateAssessmentWorkflow(workflow.id, { state: "AWAITING_APPROVAL", proposedChanges: job.pendingChanges ?? [] });
    } else if (job.status === "completed") {
      const draftHtml = job.updatedHtml;
      if (!draftHtml) throw new AssessmentGenerationError(502, "MALFORMED_RESPONSE", "SuperDocs completed the assessment without generated document HTML.");
      updateAssessmentWorkflow(workflow.id, { state: "APPROVED", draftHtml: validateGeneratedDraft(draftHtml, workflow.facts) });
    } else if (job.status === "failed" || job.status === "cancelled") {
      updateAssessmentWorkflow(workflow.id, { state: "FAILED", error: "SuperDocs could not complete the assessment workflow." });
    }
    const current = getAssessmentWorkflow(workflow.id)!;
    return Response.json({ state: current.state, proposedChanges: current.proposedChanges, draftHtml: current.draftHtml, error: current.error });
  } catch (error) {
    const message = error instanceof AssessmentGenerationError ? error.message : "Unable to retrieve assessment status.";
    return Response.json({ error: message, code: error instanceof AssessmentGenerationError ? error.code : "NETWORK" }, { status: error instanceof AssessmentGenerationError ? error.status : 502 });
  }
}
