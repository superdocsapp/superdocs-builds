import { getAuth } from "@clerk/express";
import type { RequestHandler, Response } from "express";

/**
 * Requires a signed-in Clerk user. Mount after `clerkMiddleware` (see app.ts).
 *
 * On success the verified user id is stored in `res.locals.labUserId`, which
 * handlers read via {@link authenticatedUserId}. Never trust user ids from
 * request bodies, params, or headers — this is the only identity source.
 */
export const requireAuth: RequestHandler = (req, res, next) => {
  let userId: string | null = null;
  try {
    userId = getAuth(req).userId;
  } catch {
    // clerkMiddleware not mounted or misconfigured — treat as signed out.
    userId = null;
  }
  if (!userId) {
    res.status(401).json({ error: "Authentication required." });
    return;
  }
  res.locals.labUserId = userId;
  next();
};

/** Reads the authenticated user id set by {@link requireAuth} (or a test stand-in). */
export function authenticatedUserId(res: Response): string {
  const userId = (res.locals as { labUserId?: unknown }).labUserId;
  if (typeof userId !== "string" || userId.length === 0) {
    throw new Error(
      "No authenticated user on this request. Is requireAuth mounted?",
    );
  }
  return userId;
}
