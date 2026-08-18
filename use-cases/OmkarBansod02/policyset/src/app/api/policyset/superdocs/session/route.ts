import { NextResponse } from "next/server";

import {
  getPolicySetSessionDocuments,
  initializePolicySetSession,
} from "@/superdocs";
import {
  PolicySetRequestError,
  readJsonObject,
  requiredPolicyProfile,
  routeError,
} from "../http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const body = await readJsonObject(request);
    const profile = requiredPolicyProfile(body.profile);
    const session = await initializePolicySetSession(profile);
    return NextResponse.json(session, { status: 201 });
  } catch (error) {
    return routeError(error);
  }
}

export async function GET(request: Request) {
  try {
    const sessionId = new URL(request.url).searchParams.get("sessionId");
    if (!sessionId) {
      throw new PolicySetRequestError("sessionId must be provided.");
    }
    const documents = await getPolicySetSessionDocuments(sessionId);
    return NextResponse.json({ documents });
  } catch (error) {
    return routeError(error);
  }
}
