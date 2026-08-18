import { NextResponse } from "next/server";

import { getPolicyTargetedSynchronizedJob } from "@/superdocs";
import {
  PolicySetRequestError,
  readJsonObject,
  requiredChangeSet,
  requiredDocumentIds,
  requiredPolicyDocumentType,
  requiredString,
  routeError,
} from "../../../http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ jobId: string }> },
) {
  try {
    const { jobId } = await context.params;
    if (!jobId) {
      throw new PolicySetRequestError("jobId must be provided.");
    }
    const body = await readJsonObject(request);
    const job = await getPolicyTargetedSynchronizedJob({
      jobId,
      sessionId: requiredString(body, "sessionId"),
      documentType: requiredPolicyDocumentType(body.documentType),
      documentIds: requiredDocumentIds(body.documentIds),
      changeSet: requiredChangeSet(body.changeSet),
    });
    return NextResponse.json(job);
  } catch (error) {
    return routeError(error);
  }
}
