import { Router, type IRouter, type RequestHandler } from "express";
import {
  authenticatedUserId,
  requireAuth,
} from "../middlewares/requireAuth";
import {
  deleteWorkspace,
  preferencesPayloadSchema,
  readPreferences,
  readWorkspace,
  workspacePayloadSchema,
  writePreferences,
  writeWorkspace,
} from "../lib/userData";

/**
 * User-scoped persistence routes for signed-in users.
 *
 * Every route requires authentication and only ever touches rows belonging
 * to the verified user id. The `authenticate` parameter exists so tests can
 * substitute a deterministic identity; production always uses `requireAuth`.
 */
export function createUserDataRouter(
  authenticate: RequestHandler = requireAuth,
): IRouter {
  const router: IRouter = Router();

  router.use("/user", authenticate);

  router.get("/user/workspace", async (req, res) => {
    try {
      const stored = await readWorkspace(authenticatedUserId(res));
      if (!stored) {
        res.json({ workspace: null, updatedAt: null });
        return;
      }
      res.json(stored);
    } catch (error) {
      req.log.error({ err: error }, "Failed to load workspace");
      res.status(500).json({ error: "Could not load your workspace." });
    }
  });

  router.put("/user/workspace", async (req, res) => {
    const parsed = workspacePayloadSchema.safeParse(req.body);
    if (!parsed.success) {
      req.log.warn(
        { validation: parsed.error.message },
        "Invalid workspace payload",
      );
      res.status(400).json({ error: "Invalid workspace payload." });
      return;
    }
    try {
      const savedAt = await writeWorkspace(
        authenticatedUserId(res),
        parsed.data,
      );
      res.json({ ok: true, savedAt: savedAt.toISOString() });
    } catch (error) {
      req.log.error({ err: error }, "Failed to save workspace");
      res.status(500).json({ error: "Could not save your workspace." });
    }
  });

  router.delete("/user/workspace", async (req, res) => {
    try {
      await deleteWorkspace(authenticatedUserId(res));
      res.json({ ok: true });
    } catch (error) {
      req.log.error({ err: error }, "Failed to delete workspace");
      res.status(500).json({ error: "Could not clear your workspace." });
    }
  });

  router.get("/user/preferences", async (req, res) => {
    try {
      const preferences = await readPreferences(authenticatedUserId(res));
      res.json({ preferences });
    } catch (error) {
      req.log.error({ err: error }, "Failed to load preferences");
      res.status(500).json({ error: "Could not load your preferences." });
    }
  });

  router.put("/user/preferences", async (req, res) => {
    const parsed = preferencesPayloadSchema.safeParse(req.body);
    if (!parsed.success) {
      req.log.warn(
        { validation: parsed.error.message },
        "Invalid preferences payload",
      );
      res.status(400).json({ error: "Invalid preferences payload." });
      return;
    }
    try {
      await writePreferences(authenticatedUserId(res), parsed.data);
      res.json({ ok: true });
    } catch (error) {
      req.log.error({ err: error }, "Failed to save preferences");
      res.status(500).json({ error: "Could not save your preferences." });
    }
  });

  return router;
}

const userDataRouter: IRouter = createUserDataRouter();

export default userDataRouter;
