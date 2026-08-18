import { NextResponse } from "next/server";

import { submitPolicyDocumentReview } from "@/superdocs";
import {
  readJsonObject,
  requiredBoolean,
  requiredString,
  routeError,
} from "../http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const review = await submitPolicyDocumentReview({
      sessionId: requiredString(body, "sessionId"),
      jobId: requiredString(body, "jobId"),
      selectedDocumentId: requiredString(body, "documentId"),
      approved: requiredBoolean(body, "approved"),
    });
    return NextResponse.json(review);
  } catch (error) {
    return routeError(error);
  }
}
