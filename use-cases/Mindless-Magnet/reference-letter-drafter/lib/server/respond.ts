import "server-only";
import { NextResponse } from "next/server";
import { UpstreamError } from "../http";

/**
 * One error shape for every route.
 *
 * The client gets a cause and a fix, never a stack trace and never the upstream
 * body, which can echo back the request and with it anything the user typed.
 * The server log gets the detail.
 */
export function errorResponse(err: unknown, fallbackOperation: string): NextResponse {
  if (err instanceof UpstreamError) {
    console.error(`[${err.operation}] ${err.status}: ${err.body.slice(0, 500)}`);
    const status = err.status === 0 || err.status === 408 ? 504 : err.status >= 500 ? 502 : err.status;
    return NextResponse.json(err.toClient(), { status });
  }

  const message = err instanceof Error ? err.message : String(err);
  console.error(`[${fallbackOperation}] ${message}`);

  // A missing key is a setup problem, not a server fault. Say so, and say where.
  if (message.includes("SUPERDOCS_API_KEY")) {
    return NextResponse.json(
      {
        error: `${fallbackOperation} failed`,
        cause: "No SuperDocs API key is configured",
        fix: "Copy .env.local.example to .env.local, add SUPERDOCS_API_KEY, and restart the dev server.",
        status: 500,
      },
      { status: 500 },
    );
  }

  return NextResponse.json(
    {
      error: `${fallbackOperation} failed`,
      cause: message,
      fix: "This is an unhandled error in the app. The session id in the URL is still valid; the letter is not lost.",
      status: 500,
    },
    { status: 500 },
  );
}

export function badRequest(fix: string): NextResponse {
  return NextResponse.json(
    { error: "Invalid request", cause: "The request body was missing required fields", fix, status: 400 },
    { status: 400 },
  );
}
