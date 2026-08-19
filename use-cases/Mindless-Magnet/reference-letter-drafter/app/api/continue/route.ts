import { NextResponse } from "next/server";
import { continueJob } from "@/lib/superdocs";
import { errorResponse, badRequest } from "@/lib/server/respond";

export async function POST(req: Request) {
  let body: { sessionId?: string; jobId?: string; proceed?: boolean };
  try {
    body = await req.json();
  } catch {
    return badRequest("Send a JSON body with sessionId, jobId and proceed.");
  }

  if (!body.sessionId || !body.jobId || typeof body.proceed !== "boolean") {
    return badRequest("sessionId, jobId and a boolean proceed are all required.");
  }

  try {
    const result = await continueJob({
      sessionId: body.sessionId,
      jobId: body.jobId,
      proceed: body.proceed,
    });
    return NextResponse.json(result);
  } catch (err) {
    return errorResponse(err, "Continuing the draft");
  }
}
