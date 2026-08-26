import type { OpsLedger } from "../budget.js";
import type { SuperDocsClient } from "../client.js";
import type { Client } from "../domain/clients.js";
import type { Requirement } from "../domain/requirements.js";

export class CompliancePlanParseError extends Error {
  constructor(
    message: string,
    public readonly rawResponse: string,
  ) {
    super(message);
    this.name = "CompliancePlanParseError";
  }
}

export interface CompliancePackSection {
  requirement_id: string;
  heading: string;
  intent: string;
  source_notes: string[];
}

export interface CompliancePackOutline {
  client_id: string;
  title: string;
  sections: CompliancePackSection[];
}

interface RawCompliancePlanResponse {
  outlines: CompliancePackOutline[];
}

export interface CompliancePlanResult {
  outlines: CompliancePackOutline[];
  sessionId: string;
}

/**
 * Strips a ```json fenced block down to its contents, tolerating a bare
 * ``` fence or no fence at all. Shared with coverage.ts's model-assisted
 * suitability check — same "AI returns JSON, sometimes fenced" problem.
 */
export function stripJsonFences(text: string): string {
  const trimmed = text.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1]!.trim() : trimmed;
}

/**
 * Scans from the first `{` and returns the substring up to (and including)
 * the matching close brace — respecting string literals so a `}` inside a
 * quoted value doesn't end the scan early. Returns null if the braces never
 * balance. Used to recover a response that is otherwise valid JSON but has
 * trailing garbage appended after the real close.
 */
export function extractBalancedJson(text: string): string | null {
  const start = text.indexOf("{");
  if (start === -1) return null;

  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let i = start; i < text.length; i++) {
    const ch = text[i]!;
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }

  return null;
}

/**
 * Parses a model's JSON reply defensively, in increasing order of effort:
 *  1. Fence-stripped direct parse.
 *  2. If that parses to a plain string, parse again — a genuine
 *     double-encoded payload (the whole object re-wrapped as a JSON
 *     string).
 *  3. If direct parse throws, extract the first balanced top-level
 *     `{...}` and parse that instead.
 *
 * Step 3 exists because of an observed live failure mode that isn't
 * double-encoding: the model's response is a complete, valid JSON object
 * with a stray `"}` appended after the real closing brace — roughly half
 * the time on a large outline response, confirmed by dumping the raw bytes
 * (see evidence/bugs/BUG-002). Discarding an otherwise-correct response
 * over two trailing characters is worse than recovering it.
 */
export function parseJsonLoosely<T>(raw: string): T {
  const cleaned = stripJsonFences(raw);

  const parseMaybeDoubleEncoded = (text: string): T => {
    let value: unknown = JSON.parse(text);
    if (typeof value === "string") {
      value = JSON.parse(value);
    }
    return value as T;
  };

  try {
    return parseMaybeDoubleEncoded(cleaned);
  } catch {
    const balanced = extractBalancedJson(cleaned);
    if (balanced === null) {
      throw new Error("no balanced JSON object found in response");
    }
    return parseMaybeDoubleEncoded(balanced);
  }
}

/**
 * This is a DRAFT outline only — which requirements look applicable to
 * which client, and which notes plausibly evidence them. It is not the
 * compliance determination: coverage.ts runs independently afterwards and
 * is the authority on EVIDENCED/STALE/MISSING/INCONSISTENT. Nothing this
 * function returns is trusted as a compliance claim on its own.
 */
export async function planCompliancePacks(
  client: SuperDocsClient,
  ledger: OpsLedger,
  requirements: Requirement[],
  clients: Client[],
  notesDigest: string,
): Promise<CompliancePlanResult> {
  const sessionId = `notesforge-compliance-plan-${Date.now()}`;

  // Planning every client's outline is a single chat() call regardless of
  // roster size — budget for 1 op before spending it.
  ledger.assertCanSpend(1);

  const requirementsForPrompt = requirements.map((r) => ({
    id: r.id,
    title: r.title,
    frequency: r.frequency,
    applies_to: r.applies_to,
  }));
  const clientsForPrompt = clients.map((c) => ({
    id: c.id,
    name: c.name,
    advisory_type: c.advisory_type,
    ai_assisted: c.ai_assisted,
  }));

  const message = `You are drafting the OUTLINE (not the final content) for per-client SEBI compliance packs for a fictional Indian investment advisory firm, built from a folder of compliance notes.

Respond with JSON only — no prose, no commentary, no markdown code fences. The JSON must match exactly this shape:
{"outlines": [{"client_id": string, "title": string, "sections": [{"requirement_id": string, "heading": string, "intent": string, "source_notes": string[]}]}]}

Rules:
- Produce exactly one outline per client in the roster below, using that client's exact "id".
- Only include a section for a requirement that plausibly applies to that client: skip firm-level requirements (applies_to "firm") entirely — they are not client sections. Only include "RIA-AI-01" if that client's "ai_assisted" is true.
- "heading" is a short human-readable label for the requirement — a later step attaches the actual evidence citation, so do not assert compliance in the heading text.
- "intent" is one sentence describing what that section should cover.
- "source_notes" lists filenames (the "### <filename>" headings in the digest) that plausibly relate to that client and requirement — this is a best-guess starting point for drafting, not a verified determination. If you can't find anything plausible, return an empty array rather than guessing.

Requirements register:
${JSON.stringify(requirementsForPrompt, null, 2)}

Client roster:
${JSON.stringify(clientsForPrompt, null, 2)}

Notes digest:
${notesDigest}`;

  const response = await client.chat({
    message,
    session_id: sessionId,
    model_tier: "core",
  });

  let parsed: RawCompliancePlanResponse;
  try {
    parsed = parseJsonLoosely<RawCompliancePlanResponse>(response.response);
  } catch {
    console.error(`[ERROR] planCompliancePacks: AI response was not valid JSON:\n${response.response}`);
    throw new CompliancePlanParseError(
      "planCompliancePacks: AI response was not valid JSON",
      response.response,
    );
  }

  if (!Array.isArray(parsed.outlines)) {
    throw new CompliancePlanParseError(
      'planCompliancePacks: AI response JSON had no "outlines" array',
      response.response,
    );
  }

  return { outlines: parsed.outlines, sessionId };
}
