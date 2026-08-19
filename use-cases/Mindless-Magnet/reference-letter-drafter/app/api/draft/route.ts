import { NextResponse } from "next/server";
import { createHash } from "node:crypto";
import { startDraftJob } from "@/lib/superdocs";
import { buildDraftInstruction } from "@/lib/buildInstruction";
import { once } from "@/lib/idempotency";
import { validateIntake } from "@/lib/validateIntake";
import { errorResponse, badRequest } from "@/lib/server/respond";

interface DraftRequestBody {
  sessionId?: string;
  intake?: unknown;
  /** Optional client-supplied key; derived from content when absent. */
  idempotencyKey?: string;
}

export async function POST(req: Request) {
  let body: DraftRequestBody;
  try {
    body = (await req.json()) as DraftRequestBody;
  } catch {
    return badRequest("Send a JSON body with sessionId and intake.");
  }

  if (!body.sessionId) return badRequest("sessionId is required. Call POST /api/session first.");

  const validation = validateIntake(body.intake);
  if (!validation.ok) {
    return NextResponse.json(
      {
        error: "Invalid intake",
        cause: "The intake did not pass validation",
        fix: validation.errors.join(" "),
        fieldErrors: validation.fieldErrors,
        status: 400,
      },
      { status: 400 },
    );
  }

  const intake = validation.value;
  const message = buildDraftInstruction(intake);

  // Content-derived so two identical submissions collapse even if the client
  // forgot to send a key. Includes the session so a genuine second letter in a
  // new session is never mistaken for a replay.
  const key =
    body.idempotencyKey ??
    createHash("sha256").update(`${body.sessionId}:${message}`).digest("hex");

  try {
    const { value: job, replayed } = await once(key, () =>
      startDraftJob({
        sessionId: body.sessionId!,
        message,
        memoryKey: intake.writerEmail || intake.writerName,
        templateId: intake.templateId,
      }),
    );
    return NextResponse.json({ ...job, replayed });
  } catch (err) {
    return errorResponse(err, "Starting the draft");
  }
}
