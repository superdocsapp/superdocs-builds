import { NextResponse } from "next/server";

import { getPolicyDocumentEditJob } from "@/superdocs";
import {
  PolicySetRequestError,
  routeError,
} from "../../http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ jobId: string }> },
) {
  try {
    const { jobId } = await context.params;
    const search = new URL(request.url).searchParams;
    const sessionId = search.get("sessionId");
    const selectedDocumentId = search.get("documentId");
    if (!jobId || !sessionId || !selectedDocumentId) {
      throw new PolicySetRequestError(
        "jobId, sessionId, and documentId must be provided.",
      );
    }
    const job = await getPolicyDocumentEditJob({
      jobId,
      sessionId,
      selectedDocumentId,
    });
    return NextResponse.json(job);
  } catch (error) {
    return routeError(error);
  }
}
