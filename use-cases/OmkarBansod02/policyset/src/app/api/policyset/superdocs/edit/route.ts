import { NextResponse } from "next/server";

import { startPolicyDocumentEdit } from "@/superdocs";
import {
  readJsonObject,
  requiredString,
  routeError,
} from "../http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const job = await startPolicyDocumentEdit({
      sessionId: requiredString(body, "sessionId"),
      documentId: requiredString(body, "documentId"),
      instruction: requiredString(body, "instruction"),
    });
    return NextResponse.json(job, { status: 202 });
  } catch (error) {
    return routeError(error);
  }
}
