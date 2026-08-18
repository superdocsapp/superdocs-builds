import { NextResponse } from "next/server";
import { startDraftJob } from "@/lib/superdocs";
import { buildDraftInstruction } from "@/lib/buildInstruction";
import type { Intake } from "@/lib/types";

interface DraftRequestBody {
  sessionId: string;
  intake: Intake;
}

export async function POST(req: Request) {
  const body = (await req.json()) as DraftRequestBody;

  if (!body.sessionId || !body.intake) {
    return NextResponse.json({ error: "sessionId and intake are required" }, { status: 400 });
  }

  const message = buildDraftInstruction(body.intake);
  const memoryKey = body.intake.writerEmail || body.intake.writerName;

  try {
    const job = await startDraftJob({
      sessionId: body.sessionId,
      message,
      memoryKey,
    });
    return NextResponse.json(job);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to start draft" },
      { status: 502 },
    );
  }
}
