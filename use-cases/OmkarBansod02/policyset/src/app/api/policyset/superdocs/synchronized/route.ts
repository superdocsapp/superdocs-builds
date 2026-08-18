import { NextResponse } from "next/server";

import { startPolicySynchronizedEdit } from "@/superdocs";
import {
  readJsonObject,
  requiredChangeSet,
  requiredDocumentIds,
  requiredString,
  routeError,
} from "../http";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const started = await startPolicySynchronizedEdit({
      sessionId: requiredString(body, "sessionId"),
      documentIds: requiredDocumentIds(body.documentIds),
      changeSet: requiredChangeSet(body.changeSet),
    });
    return NextResponse.json(started, { status: 202 });
  } catch (error) {
    return routeError(error);
  }
}
