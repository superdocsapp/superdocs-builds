import { NextResponse } from "next/server";
import { getJobStatus } from "@/lib/superdocs";
import { documentHtmlFromJob, pendingChangesFromJob } from "@/lib/parsePendingChanges";
import { errorResponse } from "@/lib/server/respond";

/**
 * Job status, with the pending changes already parsed.
 *
 * The double-parse happens here, on the server, once. The client receives a
 * plain array it can render. Leaving the raw JSON-encoded string to be decoded
 * in a component is how every field ends up undefined behind an approve button.
 */
export async function GET(_req: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  try {
    const job = await getJobStatus(jobId);
    const parsed = pendingChangesFromJob(job);

    return NextResponse.json({
      job_id: job.job_id,
      session_id: job.session_id,
      status: job.status,
      progress: job.progress,
      error: job.error ?? null,
      awaitingKind: job.metadata?.awaiting_kind ?? null,
      message: job.metadata?.message ?? null,
      pendingChanges: parsed.changes,
      parseProblem: parsed.problem ?? null,
      documentHtml: documentHtmlFromJob(job),
    });
  } catch (err) {
    return errorResponse(err, "Checking draft progress");
  }
}
