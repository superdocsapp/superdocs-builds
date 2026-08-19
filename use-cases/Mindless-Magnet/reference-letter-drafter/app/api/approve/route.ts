import { NextResponse } from "next/server";
import { approveChanges } from "@/lib/superdocs";
import { errorResponse, badRequest } from "@/lib/server/respond";
import type { ApproveDecision } from "@/lib/types";

interface ApproveRequestBody {
  sessionId?: string;
  jobId?: string;
  decisions?: ApproveDecision[];
}

function isDecision(value: unknown): value is ApproveDecision {
  if (!value || typeof value !== "object") return false;
  const d = value as Record<string, unknown>;
  return typeof d.change_id === "string" && typeof d.approved === "boolean";
}

export async function POST(req: Request) {
  let body: ApproveRequestBody;
  try {
    body = (await req.json()) as ApproveRequestBody;
  } catch {
    return badRequest("Send a JSON body with sessionId, jobId and decisions.");
  }

  if (!body.sessionId || !body.jobId) {
    return badRequest("sessionId and jobId are both required.");
  }

  const decisions = body.decisions ?? [];
  if (decisions.length === 0) return badRequest("At least one decision is required.");
  if (!decisions.every(isDecision)) {
    return badRequest("Every decision needs a change_id string and an approved boolean.");
  }

  // Duplicate ids would make the outcome depend on upstream ordering. Refuse
  // rather than silently picking one.
  const ids = new Set(decisions.map((d) => d.change_id));
  if (ids.size !== decisions.length) {
    return badRequest("The same change was decided more than once. Submit one decision per change.");
  }

  try {
    const result = await approveChanges({
      sessionId: body.sessionId,
      jobId: body.jobId,
      changes: decisions,
    });
    return NextResponse.json({
      ...result,
      approved: decisions.filter((d) => d.approved).length,
      rejected: decisions.filter((d) => !d.approved).length,
    });
  } catch (err) {
    return errorResponse(err, "Submitting your decisions");
  }
}
