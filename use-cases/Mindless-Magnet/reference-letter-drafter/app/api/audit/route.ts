import { NextResponse } from "next/server";
import { runAudit } from "@/lib/calibration";
import { validateIntake } from "@/lib/validateIntake";
import { errorResponse, badRequest } from "@/lib/server/respond";
import { getJobStatus } from "@/lib/superdocs";
import { documentHtmlFromJob, pendingChangesFromJob } from "@/lib/parsePendingChanges";

/**
 * Runs the calibration audit over a letter.
 *
 * Two input modes. Pass `letterHtml` to audit text the client already holds
 * (the proposed-changes preview, before anything is committed) or pass `jobId`
 * to have the server pull the current document from SuperDocs. Auditing the
 * proposal rather than the committed document is the point: findings have to
 * reach the writer while the gate is still closed.
 */
export async function POST(req: Request) {
  let body: { intake?: unknown; letterHtml?: string; jobId?: string };
  try {
    body = await req.json();
  } catch {
    return badRequest("Send a JSON body with intake and either letterHtml or jobId.");
  }

  const validation = validateIntake(body.intake);
  if (!validation.ok) {
    return NextResponse.json(
      { error: "Invalid intake", cause: "Validation failed", fix: validation.errors.join(" "), status: 400 },
      { status: 400 },
    );
  }

  let letterHtml = body.letterHtml ?? "";

  if (!letterHtml && body.jobId) {
    try {
      const job = await getJobStatus(body.jobId);
      letterHtml = documentHtmlFromJob(job);
      if (!letterHtml) {
        // Fall back to the proposed text: a job awaiting approval has no
        // committed document yet, and that is exactly when the audit matters.
        letterHtml = pendingChangesFromJob(job)
          .changes.map((change) => change.new_html)
          .join("\n");
      }
    } catch (err) {
      return errorResponse(err, "Fetching the letter to audit");
    }
  }

  if (!letterHtml.trim()) {
    return badRequest("There is no letter text to audit yet. Wait for the draft to produce changes.");
  }

  try {
    const report = await runAudit({ letterHtml, intake: validation.value });
    return NextResponse.json(report);
  } catch (err) {
    return errorResponse(err, "Running the calibration audit");
  }
}
