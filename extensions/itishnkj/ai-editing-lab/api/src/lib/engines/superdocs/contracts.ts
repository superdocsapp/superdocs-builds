export type SuperdocsPendingChange = {
  changeId: string;
  operation: "edit" | "create" | "delete";
  oldHtml: string | null;
  newHtml: string | null;
  explanation: string | null;
  target: string | null;
  chunkId: string | null;
};

export type SuperdocsStartReviewBody = {
  session_id: string;
  document_html: string;
  message: string;
  approval_mode: "ask_every_time";
  model_tier: string;
  thinking_depth: string;
};

export type SuperdocsDecisionBody = {
  job_id: string;
  approved: boolean;
  changes: Array<{
    change_id: string;
    approved: boolean;
    feedback: string | null;
  }>;
};

function readString(
  value: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string") return candidate;
  }
  return null;
}

function readOperation(value: Record<string, unknown>): "edit" | "create" | "delete" {
  const operation = readString(value, ["operation", "type", "action"])?.toLowerCase();
  if (operation === "create" || operation === "insert" || operation === "add") {
    return "create";
  }
  if (operation === "delete" || operation === "remove") return "delete";
  return "edit";
}

export function normalizePendingChanges(job: {
  metadata?: Record<string, unknown>;
}): SuperdocsPendingChange[] {
  const pending = job.metadata?.pending_changes;
  if (!Array.isArray(pending)) return [];

  return pending.flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const change = entry as Record<string, unknown>;
    const changeId = readString(change, ["change_id", "id"]);
    if (!changeId) return [];
    return [{
      changeId,
      operation: readOperation(change),
      oldHtml: readString(change, [
        "old_html",
        "original_html",
        "before_html",
        "source_html",
      ]),
      newHtml: readString(change, [
        "new_html",
        "proposed_html",
        "after_html",
        "replacement_html",
      ]),
      explanation: readString(change, [
        "ai_explanation",
        "explanation",
        "reason",
      ]),
      target: readString(change, ["target", "section_title", "label"]),
      chunkId: readString(change, ["chunk_id", "target_chunk_id"]),
    }];
  });
}

export function buildStartReviewBody(input: {
  sessionId: string;
  documentHtml: string;
  message: string;
  modelTier: string;
  thinkingDepth: string;
}): SuperdocsStartReviewBody {
  return {
    session_id: input.sessionId,
    document_html: input.documentHtml,
    message: input.message,
    approval_mode: "ask_every_time",
    model_tier: input.modelTier,
    thinking_depth: input.thinkingDepth,
  };
}

export function buildDecisionBody(input: {
  jobId: string;
  decisions: Array<{ changeId: string; approved: boolean; feedback?: string | null }>;
}): SuperdocsDecisionBody {
  return {
    job_id: input.jobId,
    approved: input.decisions.every((decision) => decision.approved),
    changes: input.decisions.map((decision) => ({
      change_id: decision.changeId,
      approved: decision.approved,
      feedback: decision.feedback ?? null,
    })),
  };
}