import { NextResponse } from "next/server";
import { approveChange } from "@/lib/superdocs";
import type { ApproveDecision } from "@/lib/types";

interface ApproveRequestBody {
  sessionId: string;
  jobId: string;
  decisions: ApproveDecision[];
}

export async function POST(req: Request) {
  const body = (await req.json()) as ApproveRequestBody;

  if (!body.sessionId || !body.jobId || !body.decisions?.length) {
    return NextResponse.json(
      { error: "sessionId, jobId, and decisions are required" },
      { status: 400 },
    );
  }

  try {
    const result = await approveChange({
      sessionId: body.sessionId,
      jobId: body.jobId,
      // Top-level `approved` is required by the SuperDocs API even for
      // per-change batches; it's the default for any entry that omits its
      // own `approved`. Every entry here sets its own, so this value is
      // unused but still mandatory.
      approved: true,
      changes: body.decisions,
    });
    return NextResponse.json(result);
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Failed to submit approval" },
      { status: 502 },
    );
  }
}
