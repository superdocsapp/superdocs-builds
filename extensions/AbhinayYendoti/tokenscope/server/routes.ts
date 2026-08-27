import express, { type Request, type Response, type Router } from "express";
import { assertInstruction, InvalidSelectionError, resolveSelection } from "../shared/selection.js";
import { measure } from "../shared/tokens.js";
import type { AccountStatus, DocumentSnapshot, JobWork } from "../shared/types.js";
import { getConfig } from "./config.js";
import { TokenScopeError, toErrorBody } from "./errors.js";
import { applyChange, measureWholeDocument, rewriteSelection } from "./rewrite.js";
import { whoami } from "./superdocs.js";

/**
 * The HTTP surface. Four routes, one job each.
 *
 * The API key never crosses this boundary: the browser asks TokenScope, and
 * TokenScope asks SuperDocs. `/api/status` reports whether a key is present
 * without revealing anything about it.
 */

interface DocumentBody {
  document?: unknown;
  selectedText?: unknown;
  instruction?: unknown;
}

interface WholeDocumentBody extends DocumentBody {
  surgical?: unknown;
}

/** The surgical run the pane is asking us to compare against. */
function readSurgical(value: unknown): { work: JobWork; reportedTokens: number | null } {
  const surgical = value as { work?: unknown; reportedTokens?: unknown } | null;
  const work = surgical?.work as JobWork | undefined;

  if (
    work === undefined ||
    typeof work.sectionsChanged !== "number" ||
    typeof work.output?.tokens !== "number"
  ) {
    throw new TokenScopeError(
      "invalid_selection",
      "The request did not include the surgical run to compare against."
    );
  }

  return {
    work,
    reportedTokens: typeof surgical?.reportedTokens === "number" ? surgical.reportedTokens : null
  };
}

function readDocument(value: unknown): DocumentSnapshot {
  if (
    value === null ||
    typeof value !== "object" ||
    !Array.isArray((value as { paragraphs?: unknown }).paragraphs)
  ) {
    throw new TokenScopeError("invalid_selection", "The request did not include a document.");
  }

  const paragraphs = (value as { paragraphs: unknown[] }).paragraphs.map((p, index) => {
    if (p === null || typeof p !== "object") {
      throw new TokenScopeError("invalid_selection", `Paragraph ${index} is malformed.`);
    }

    const { id, text } = p as { id?: unknown; text?: unknown };

    if (typeof id !== "string" || typeof text !== "string") {
      throw new TokenScopeError("invalid_selection", `Paragraph ${index} is missing id or text.`);
    }

    return { id, text };
  });

  if (paragraphs.length === 0) {
    throw new TokenScopeError("invalid_selection", "The document is empty.");
  }

  return { paragraphs };
}

function readString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new TokenScopeError("invalid_selection", `Expected ${field} to be a string.`);
  }

  return value;
}

/** InvalidSelectionError is domain-level; give it the right code for the pane. */
function rethrow(error: unknown): never {
  if (error instanceof InvalidSelectionError) {
    const empty = error.message.startsWith("Enter a rewrite instruction");
    throw new TokenScopeError(empty ? "empty_instruction" : "invalid_selection", error.message);
  }

  throw error;
}

async function handle(res: Response, work: () => Promise<unknown>): Promise<void> {
  try {
    res.json(await work());
  } catch (error) {
    const { status, body } = toErrorBody(error);

    if (status >= 500 && !(error instanceof TokenScopeError)) {
      console.error("[tokenscope] unhandled", error);
    }

    res.status(status).json(body);
  }
}

export function createRouter(): Router {
  const router = express.Router();

  router.get("/status", (_req: Request, res: Response) => {
    void handle(res, async (): Promise<AccountStatus> => {
      const { configured } = getConfig();

      if (!configured) {
        return {
          configured: false,
          problem:
            "SUPERDOCS_API_KEY is not set. Copy .env.example to .env.local, add your key, " +
            "and restart the server."
        };
      }

      try {
        const account = await whoami();
        const quota = account.quota;

        return {
          configured: true,
          ...(account.tier === undefined ? {} : { tier: account.tier }),
          ...(quota === undefined
            ? {}
            : {
                quota: {
                  monthlyLimit: quota.monthly_limit,
                  used: quota.used,
                  remaining: quota.remaining,
                  resetsAt: quota.resets_at ?? null
                }
              })
        };
      } catch (error) {
        return {
          configured: true,
          problem: error instanceof Error ? error.message : "SuperDocs is unreachable."
        };
      }
    });
  });

  router.post("/rewrite", (req: Request, res: Response) => {
    void handle(res, async () => {
      const body = req.body as DocumentBody;
      const document = readDocument(body.document);

      try {
        const selection = resolveSelection(document, readString(body.selectedText, "selectedText"));
        const instruction = assertInstruction(readString(body.instruction, "instruction"));

        return await rewriteSelection({ document, selection, instruction });
      } catch (error) {
        rethrow(error);
      }
    });
  });

  /**
   * Run the counterfactual for real, and return the whole comparison again.
   *
   * The recomputed measurement is built here rather than in the pane so the
   * tokenizer stays on the server: a Word task pane should not be downloading
   * two megabytes of BPE tables to count a paragraph.
   */
  router.post("/whole-document", (req: Request, res: Response) => {
    void handle(res, async () => {
      const body = req.body as WholeDocumentBody;
      const document = readDocument(body.document);

      try {
        const instruction = assertInstruction(readString(body.instruction, "instruction"));
        const selection = resolveSelection(document, readString(body.selectedText, "selectedText"));
        const surgical = readSurgical(body.surgical);
        const run = await measureWholeDocument({ document, instruction });

        return {
          run,
          measurement: measure({
            document,
            selection,
            surgicalWork: surgical.work,
            reportedSurgicalTokens: surgical.reportedTokens,
            wholeDocumentWork: run.work,
            reportedWholeDocumentTokens: run.reportedTokens
          })
        };
      } catch (error) {
        rethrow(error);
      }
    });
  });

  router.post("/apply", (req: Request, res: Response) => {
    void handle(res, async () => {
      const body = req.body as { sessionId?: unknown; jobId?: unknown; changeId?: unknown };

      return applyChange({
        sessionId: readString(body.sessionId, "sessionId"),
        jobId: readString(body.jobId, "jobId"),
        changeId: readString(body.changeId, "changeId")
      });
    });
  });

  return router;
}
