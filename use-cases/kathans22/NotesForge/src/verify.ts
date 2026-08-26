import type { OpsLedger } from "./budget.js";
import type { SuperDocsClient } from "./client.js";
import type { ReportPlan } from "./pipeline.js";
import type { DocumentHeading } from "./types.js";

function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

export interface VerifyResult {
  ok: boolean;
  missing: string[];
  unexpected: string[];
  sectionCount: number;
  blockCount: number;
  headings: DocumentHeading[];
}

function logHeadingTree(headings: DocumentHeading[]): void {
  console.log("[INFO] document structure:");
  for (const h of headings) {
    console.log(`${"  ".repeat(Math.max(h.level - 1, 0))}- (h${h.level}) ${h.text}`);
  }
}

/**
 * Compares the document's actual headings against the approved plan.
 */
export async function verifyStructure(
  client: SuperDocsClient,
  documentId: string,
  plan: ReportPlan,
): Promise<VerifyResult> {
  // include_html defaults to false — `structure` is derived on read and is
  // never billed, so this check is always free. Never spend an export just
  // to see whether an edit landed.
  const { structure } = await client.getDocument(documentId);

  logHeadingTree(structure.headings);

  const actual = new Set(structure.headings.map((h) => normalise(h.text)));
  const expected = plan.sections.map((s) => ({ heading: s.heading, key: normalise(s.heading) }));

  const missing = expected.filter((e) => !actual.has(e.key)).map((e) => e.heading);

  const expectedKeys = new Set(expected.map((e) => e.key));
  const unexpected = structure.headings
    .filter((h) => !expectedKeys.has(normalise(h.text)))
    .map((h) => h.text);

  const ok = missing.length === 0;
  if (ok) {
    console.log(`[OK] structure verified — all ${plan.sections.length} planned section(s) present`);
  } else {
    console.warn(
      `[WARN] structure verification found ${missing.length} missing section(s): ${missing.join(", ")}`,
    );
  }

  return {
    ok,
    missing,
    unexpected,
    sectionCount: structure.section_count,
    blockCount: structure.block_count,
    headings: structure.headings,
  };
}

/**
 * One batched chat call naming every missing section — never one call per
 * section, since a multi-section edit bills a single operation.
 */
export async function repairMissingSections(
  client: SuperDocsClient,
  ledger: OpsLedger,
  sessionId: string,
  missing: string[],
): Promise<void> {
  if (missing.length === 0) return;

  ledger.assertCanSpend(1);

  const instructions = missing
    .map((heading) => `- Add a section titled "${heading}" in a sensible position among the existing sections.`)
    .join("\n");

  console.log(`[INFO] repairing ${missing.length} missing section(s) in one batched request`);

  await client.chat({
    message: `The document is missing the following planned section(s). Add ALL of them in this single turn, each in a sensible place relative to the existing sections:\n${instructions}`,
    session_id: sessionId,
  });
}
