import type { SuperDocsClient } from "../client.js";
import type { CoverageStatus } from "./coverage.js";
import type { PlannedPackSection } from "./generate.js";

function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

export interface ComplianceVerifyResult {
  ok: boolean;
  missingSections: string[];
  uncitedClaims: string[];
}

// A section flagging STALE or INCONSISTENT is still making a claim about
// what the evidence shows — it needs a citation exactly as much as a clean
// EVIDENCED pass does. Only MISSING is exempt, because MISSING is the
// absence of a claim.
const CLAIM_STATUSES: ReadonlySet<CoverageStatus> = new Set(["EVIDENCED", "STALE", "INCONSISTENT"]);

/**
 * Reuses the free structure read (headings only, never billed) rather than
 * spending anything to check a draft. Matches each planned section by its
 * bare requirement title — not the full citation-bearing heading — so a
 * section that landed but lost its citation is caught as an uncited claim
 * rather than mis-reported as a missing section.
 */
export async function verifyCompliancePack(
  client: SuperDocsClient,
  documentId: string,
  plannedSections: PlannedPackSection[],
): Promise<ComplianceVerifyResult> {
  const { structure } = await client.getDocument(documentId);

  console.log("[INFO] compliance pack structure:");
  for (const h of structure.headings) {
    console.log(`${"  ".repeat(Math.max(h.level - 1, 0))}- (h${h.level}) ${h.text}`);
  }

  const missingSections: string[] = [];
  const uncitedClaims: string[] = [];

  for (const section of plannedSections) {
    const titleKey = normalise(section.title);
    const actual = structure.headings.find((h) => normalise(h.text).startsWith(titleKey));

    if (!actual) {
      missingSections.push(section.heading);
      continue;
    }

    if (CLAIM_STATUSES.has(section.status) && !/\(.+\)/.test(actual.text)) {
      uncitedClaims.push(actual.text);
    }
  }

  const ok = missingSections.length === 0 && uncitedClaims.length === 0;

  if (ok) {
    console.log(
      `[OK] compliance pack verified — all ${plannedSections.length} planned section(s) present, claims cited`,
    );
  } else {
    if (missingSections.length > 0) {
      console.warn(
        `[WARN] compliance pack missing ${missingSections.length} planned section(s): ${missingSections.join(", ")}`,
      );
    }
    if (uncitedClaims.length > 0) {
      console.warn(
        `[WARN] compliance pack FAILED verification — ${uncitedClaims.length} section(s) claim a requirement is met/flagged with no citation: ${uncitedClaims.join(", ")}`,
      );
    }
  }

  return { ok, missingSections, uncitedClaims };
}
