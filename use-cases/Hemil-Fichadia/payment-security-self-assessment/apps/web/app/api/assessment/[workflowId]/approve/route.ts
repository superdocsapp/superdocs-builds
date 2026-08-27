import { getAssessmentWorkflow, updateAssessmentWorkflow } from "@/lib/server/assessment-workflow";
import { approveAssessmentChanges, AssessmentGenerationError } from "@/lib/server/superdocs";

export const runtime = "nodejs";

export async function POST(_: Request, { params }: { params: Promise<{ workflowId: string }> }) {
  const { workflowId } = await params;
  const workflow = getAssessmentWorkflow(workflowId);
  if (!workflow) return Response.json({ error: "Assessment workflow was not found. Start generation again.", code: "WORKFLOW_NOT_FOUND" }, { status: 404 });
  if (workflow.state !== "AWAITING_APPROVAL" || workflow.proposedChanges.length === 0) {
    return Response.json({ error: "Assessment changes are not ready for approval.", code: "NOT_READY" }, { status: 409 });
  }

  try {
    await approveAssessmentChanges(workflow.sessionId, workflow.jobId, workflow.proposedChanges);
    updateAssessmentWorkflow(workflow.id, { state: "APPROVING" });
    return Response.json({ state: "APPROVING" });
  } catch (error) {
    const message = error instanceof AssessmentGenerationError ? error.message : "Unable to approve assessment changes.";
    return Response.json({ error: message, code: error instanceof AssessmentGenerationError ? error.code : "NETWORK" }, { status: error instanceof AssessmentGenerationError ? error.status : 502 });
  }
}
