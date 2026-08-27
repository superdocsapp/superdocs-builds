import { canExportAssessment, getAssessmentWorkflow } from "@/lib/server/assessment-workflow";
import { AssessmentGenerationError, exportApprovedAssessment } from "@/lib/server/superdocs";

export const runtime = "nodejs";

export async function GET(_: Request, { params }: { params: Promise<{ workflowId: string }> }) {
  const { workflowId } = await params;
  const workflow = getAssessmentWorkflow(workflowId);
  if (!workflow) return Response.json({ error: "Assessment workflow was not found. Start generation again.", code: "WORKFLOW_NOT_FOUND" }, { status: 404 });
  if (!canExportAssessment(workflow)) return Response.json({ error: "Approve the assessment changes before exporting.", code: "NOT_APPROVED" }, { status: 409 });

  try {
    const exported = await exportApprovedAssessment(workflow.sessionId);
    return new Response(exported.bytes, { headers: { "Content-Type": exported.contentType, "Content-Disposition": `attachment; filename="${exported.filename}"`, "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof AssessmentGenerationError ? error.message : "Unable to export the assessment.";
    return Response.json({ error: message, code: error instanceof AssessmentGenerationError ? error.code : "NETWORK" }, { status: error instanceof AssessmentGenerationError ? error.status : 502 });
  }
}
