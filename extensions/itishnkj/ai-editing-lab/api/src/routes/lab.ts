import { Router, type IRouter } from "express";
import {
  CancelReviewBody,
  CancelReviewResponse,
  DecideReviewBody,
  DecideReviewResponse,
  GenerateEditBody,
  GenerateEditResponse,
  GetLabConfigResponse,
} from "@workspace/api-zod";
import {
  EngineUnavailableError,
  getEditingEngine,
  superdocsEngine,
} from "../lib/engines";
import { getSuperdocsPublicConfig } from "../lib/engines/superdocs/superdocsEngine";

const router: IRouter = Router();

router.get("/lab/config", (_req, res): void => {
  const diyConfigured = Boolean(
    process.env.OPENAI_API_KEY && process.env.OPENAI_MODEL,
  );
  const superdocs = getSuperdocsPublicConfig();
  const data = GetLabConfigResponse.parse({
    engines: [
      {
        id: "diy",
        label: "DIY Toolkit",
        configured: diyConfigured,
        modelLabel: process.env.OPENAI_MODEL ?? null,
        capabilities: [
          "selection editing",
          "whole-document editing",
          "structured JSON",
          "one repair retry",
          "token usage",
        ],
      },
      {
        id: "superdocs",
        label: "SuperDocs Hosted",
        configured: superdocs.configured,
        modelLabel: superdocs.modelLabel,
        modelTier: superdocs.modelTier,
        thinkingDepth: superdocs.thinkingDepth,
        capabilities: [
          "asynchronous review jobs",
          "chunk-level HTML proposals",
          "explicit approval and denial",
          "bounded server-side polling",
        ],
      },
    ],
    appMode:
      process.env.APP_MODE === "diy" ||
      process.env.APP_MODE === "superdocs"
        ? process.env.APP_MODE
        : "compare",
  });
  res.json(data);
});

function safeHostedErrorMessage(error: unknown): string {
  if (error instanceof EngineUnavailableError) return error.message;
  if (
    error instanceof Error &&
    error.message.includes("still processing this review")
  ) {
    return "SuperDocs took longer than expected to prepare this review. The job was cancelled before any document change was applied. Try again shortly.";
  }
  return "The hosted review could not be completed. Try again shortly.";
}

router.post("/lab/edits", async (req, res): Promise<void> => {
  const parsed = GenerateEditBody.safeParse(req.body);
  if (!parsed.success) {
    req.log.warn({ validation: parsed.error.message }, "Invalid edit request");
    res.status(400).json({ error: parsed.error.message });
    return;
  }

  try {
    const engine = getEditingEngine(parsed.data.engine);
    const result = await engine.edit(parsed.data);
    res.json(GenerateEditResponse.parse(result));
  } catch (error) {
    const message =
      parsed.data.engine === "superdocs"
        ? safeHostedErrorMessage(error)
        : error instanceof EngineUnavailableError
          ? error.message
          : "The editing request failed.";
    if (error instanceof EngineUnavailableError) {
      res.status(409).json({ error: message });
      return;
    }
    req.log.error(
      { err: error, engine: parsed.data.engine },
      "Editing request failed",
    );
    res.status(500).json({ error: message });
  }
});

router.post("/lab/reviews/decide", async (req, res): Promise<void> => {
  const parsed = DecideReviewBody.safeParse(req.body);
  if (!parsed.success) {
    req.log.warn({ validation: parsed.error.message }, "Invalid review decision");
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  try {
    const result = await superdocsEngine.decideReview(parsed.data);
    res.json(DecideReviewResponse.parse(result));
  } catch (error) {
    const message = safeHostedErrorMessage(error);
    if (error instanceof EngineUnavailableError) {
      res.status(409).json({ error: message });
      return;
    }
    req.log.error({ err: error }, "Hosted review decision failed");
    res.status(502).json({ error: message });
  }
});

router.post("/lab/reviews/cancel", async (req, res): Promise<void> => {
  const parsed = CancelReviewBody.safeParse(req.body);
  if (!parsed.success) {
    req.log.warn({ validation: parsed.error.message }, "Invalid review cancellation");
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  try {
    const result = await superdocsEngine.cancelReview(parsed.data.reviewId);
    res.json(CancelReviewResponse.parse(result));
  } catch (error) {
    const message = safeHostedErrorMessage(error);
    if (error instanceof EngineUnavailableError) {
      res.status(409).json({ error: message });
      return;
    }
    req.log.error({ err: error }, "Hosted review cancellation failed");
    res.status(502).json({ error: message });
  }
});

export default router;