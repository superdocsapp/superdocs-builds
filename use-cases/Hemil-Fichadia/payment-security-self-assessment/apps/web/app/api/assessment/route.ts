import { evidenceFactsMatchDeterministicClassification } from "@payment-security-self-assessment/evidence";
import { parseEvidenceFacts } from "@payment-security-self-assessment/shared";
import {
  AssessmentGenerationError,
  startAssessmentReview,
} from "@/lib/server/superdocs";
import { createAssessmentWorkflow } from "@/lib/server/assessment-workflow";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as unknown;
    const facts = parseEvidenceFacts(
      typeof body === "object" && body !== null && "facts" in body
        ? (body as { facts: unknown }).facts
        : undefined,
    );
    if (!evidenceFactsMatchDeterministicClassification(facts)) {
      return Response.json(
        { error: "Evidence facts do not match the server-side classification rules.", code: "INVALID_EVIDENCE" },
        { status: 400 },
      );
    }

    const started = await startAssessmentReview(facts);
    const workflow = createAssessmentWorkflow(started.sessionId, started.jobId, facts);
    return Response.json({ workflowId: workflow.id, state: workflow.state });
  } catch (error) {
    if (error instanceof AssessmentGenerationError) {
      return Response.json(
        { error: error.message, code: error.code },
        { status: error.status },
      );
    }

    if (error instanceof Error) {
      return Response.json({ error: error.message, code: "INVALID_EVIDENCE" }, { status: 400 });
    }

    return Response.json(
      {
        error: "Unable to generate the assessment draft. Please try again.",
        code: "UNEXPECTED",
      },
      { status: 500 },
    );
  }
}
