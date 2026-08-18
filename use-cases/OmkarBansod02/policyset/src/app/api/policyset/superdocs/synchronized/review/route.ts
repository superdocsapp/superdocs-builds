import { NextResponse } from "next/server";

import { submitPolicyTargetedSynchronizedReview } from "@/superdocs";
import {
  readJsonObject,
  requiredBoolean,
  requiredChangeSet,
  requiredDocumentIds,
  requiredPolicyDocumentType,
  requiredString,
  routeError,
} from "../../http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const review = await submitPolicyTargetedSynchronizedReview({
      sessionId: requiredString(body, "sessionId"),
      jobId: requiredString(body, "jobId"),
      documentType: requiredPolicyDocumentType(body.documentType),
      documentIds: requiredDocumentIds(body.documentIds),
      changeSet: requiredChangeSet(body.changeSet),
      approved: requiredBoolean(body, "approved"),
    });
    return NextResponse.json(review);
  } catch (error) {
    return routeError(error);
  }
}
