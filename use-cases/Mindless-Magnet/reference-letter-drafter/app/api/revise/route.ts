import { NextResponse } from "next/server";
import { createHash } from "node:crypto";
import { startDraftJob } from "@/lib/superdocs";
import { once } from "@/lib/idempotency";
import { errorResponse, badRequest } from "@/lib/server/respond";

/**
 * A freeform revision request on an existing session, outside the structured
 * intake. Same SuperDocs call as the initial draft (`chat/async`,
 * `ask_every_time`), so the result flows through the same approve/reject
 * review already built — a revision is not auto-applied any more than the
 * first draft was.
 */

const MAX_MESSAGE_LENGTH = 2000;

interface ReviseRequestBody {
  sessionId?: string;
  message?: string;
  memoryKey?: string;
  idempotencyKey?: string;
}

export async function POST(req: Request) {
  let body: ReviseRequestBody;
  try {
    body = (await req.json()) as ReviseRequestBody;
  } catch {
    return badRequest("Send a JSON body with sessionId and message.");
  }

  if (!body.sessionId) return badRequest("sessionId is required.");

  const message = body.message?.trim();
  if (!message) return badRequest("message is required.");
  if (message.length > MAX_MESSAGE_LENGTH) {
    return badRequest(`message must be ${MAX_MESSAGE_LENGTH} characters or fewer.`);
  }

  const key =
    body.idempotencyKey ??
    createHash("sha256").update(`${body.sessionId}:revise:${message}`).digest("hex");

  try {
    const { value: job, replayed } = await once(key, () =>
      startDraftJob({
        sessionId: body.sessionId!,
        message,
        memoryKey: body.memoryKey || body.sessionId!,
      }),
    );
    return NextResponse.json({ ...job, replayed });
  } catch (err) {
    return errorResponse(err, "Sending the revision request");
  }
}
