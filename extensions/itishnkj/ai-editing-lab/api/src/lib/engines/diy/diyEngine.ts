import { randomUUID } from "node:crypto";
import {
  type EditingEngine,
  type EngineEditRequest,
  type EngineEditResult,
  type EngineUsage,
} from "../types";
import { validateDocumentHtml } from "../validation";
import { createDiyCompletion } from "./client";
import {
  buildDiyMessages,
  buildRepairMessage,
  diyContextChars,
  DIY_PROMPT_VERSION,
} from "./prompt";
import { parseWithOneRepair } from "./parser";

class DiyEngine implements EditingEngine {
  readonly id = "diy" as const;
  readonly label = "DIY Toolkit";

  async edit(request: EngineEditRequest): Promise<EngineEditResult> {
    const safeRequest = {
      ...request,
      documentHtml: validateDocumentHtml(request.documentHtml),
      selectionHtml: request.selectionHtml
        ? validateDocumentHtml(request.selectionHtml)
        : request.selectionHtml,
    };
    const startedAt = new Date();
    const initialMessages = buildDiyMessages(safeRequest);
    const initialCompletion = await createDiyCompletion(initialMessages);
    const completions = [initialCompletion];
    const promptAttempts: Array<Array<{ content: string }>> = [initialMessages];
    let finalCompletion = initialCompletion;
    const parsedResult = await parseWithOneRepair(
      initialCompletion.content,
      async () => {
        const repairMessages = [
          ...buildDiyMessages(safeRequest),
          { role: "assistant" as const, content: initialCompletion.content },
          buildRepairMessage(initialCompletion.content),
        ];
        finalCompletion = await createDiyCompletion(repairMessages);
        completions.push(finalCompletion);
        promptAttempts.push(repairMessages);
        return finalCompletion.content;
      },
    );
    const parsed = parsedResult.parsed;

    const replacementHtml = validateDocumentHtml(parsed.replacement_html);
    const completedAt = new Date();
    const oldHtml =
      safeRequest.scope === "selection"
        ? safeRequest.selectionHtml || safeRequest.selectionText || null
        : safeRequest.documentHtml;

    return {
      engine: this.id,
      engineLabel: this.label,
      promptVersion: DIY_PROMPT_VERSION,
      requestId: safeRequest.requestId,
      success: true,
      proposedChanges: [
        {
          id: randomUUID(),
          operation: oldHtml ? "edit" : "create",
          oldHtml,
          newHtml: replacementHtml,
          explanation: `${parsed.explanation} (${DIY_PROMPT_VERSION})`,
          target:
            safeRequest.scope === "selection"
              ? `${safeRequest.selectionFrom ?? "?"}:${safeRequest.selectionTo ?? "?"}`
              : "document",
          chunkId: null,
          status: "pending",
        },
      ],
      candidateDocumentHtml:
        safeRequest.scope === "document" ? replacementHtml : null,
      assistantMessage: parsed.explanation,
      latencyMs: completedAt.getTime() - startedAt.getTime(),
      reviewWaitMs: null,
      usage: aggregateDiyUsage(completions.map((completion) => completion.usage)),
      retryCount: parsedResult.retryCount,
      requestMetrics: aggregateDiyRequestMetrics(
        promptAttempts,
        diyContextChars(safeRequest),
      ),
      error: null,
      review: null,
      startedAt: startedAt.toISOString(),
      completedAt: completedAt.toISOString(),
    };
  }
}

export function aggregateDiyUsage(usages: EngineUsage[]): EngineUsage {
  const sum = (field: keyof Pick<
    EngineUsage,
    "inputTokens" | "outputTokens" | "totalTokens"
  >) =>
    usages.every((usage) => usage[field] != null)
      ? usages.reduce((total, usage) => total + (usage[field] ?? 0), 0)
      : null;
  return {
    inputTokens: sum("inputTokens"),
    outputTokens: sum("outputTokens"),
    totalTokens: sum("totalTokens"),
    hostedUsage: null,
  };
}

function messageChars(messages: Array<{ content: string }>): number {
  return messages.reduce((total, message) => total + message.content.length, 0);
}

export function aggregateDiyRequestMetrics(
  attempts: Array<Array<{ content: string }>>,
  contextChars: number,
) {
  const chars = attempts.reduce(
    (total, messages) => total + messageChars(messages),
    0,
  );
  return {
    promptChars: chars,
    // Repairs resend the same source document/selection context, but do not
    // turn system instructions or the malformed response into document context.
    contextChars: contextChars * attempts.length,
  };
}

export const diyEngine = new DiyEngine();