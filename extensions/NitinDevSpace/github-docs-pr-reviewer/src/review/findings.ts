import { createHash } from "node:crypto";
import type { LineAutofix } from "./patches.js";

export type FindingSeverity = "blocker" | "warning" | "suggestion";
export type FindingCategory =
  | "style"
  | "structure"
  | "stale-reference"
  | "broken-link"
  | "preview"
  | "release";
export type FindingConfidence = "high" | "medium" | "low";
export type FindingSource = "rule" | "superdocs" | "link-checker" | "llm";

export type Finding = {
  id: string;
  severity: FindingSeverity;
  category: FindingCategory;
  path: string;
  startLine: number;
  endLine?: number;
  title: string;
  explanation: string;
  suggestedPatch?: string;
  confidence: FindingConfidence;
  source: FindingSource;
  /**
   * Present only when the fix is mechanical enough to apply without inventing
   * content. Findings without an autofix are advisory: a human writes the fix.
   */
  autofix?: LineAutofix;
};

export type FindingInput = Omit<Finding, "id"> & {
  idSeed?: string;
};

export function createFinding(input: FindingInput): Finding {
  const idSeed = [
    input.idSeed,
    input.path,
    input.startLine,
    input.category,
    input.title
  ]
    .filter(Boolean)
    .join(":");

  return {
    ...input,
    suggestedPatch: input.suggestedPatch ?? input.autofix?.after,
    id: stableFindingId(idSeed)
  };
}

export type AutofixableFinding = Finding & { autofix: LineAutofix };

export function isAutofixable(finding: Finding): finding is AutofixableFinding {
  return finding.autofix !== undefined;
}

export function stableFindingId(seed: string): string {
  return createHash("sha1").update(seed).digest("hex").slice(0, 10);
}

