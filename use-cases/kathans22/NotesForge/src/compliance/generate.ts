import { CONFIG } from "../config.js";
import type { OpsLedger } from "../budget.js";
import type { SuperDocsClient } from "../client.js";
import type { Client } from "../domain/clients.js";
import type { Requirement } from "../domain/requirements.js";
import { JobCancelledError, JobFailedError, JobTimeoutError } from "../pipeline.js";
import { canonicalSectionHeading, type CoverageEntry, type CoverageStatus } from "./coverage.js";
import type { CompliancePackOutline } from "./plan.js";

export const DRAFT_BANNER =
  "DRAFT FOR PROFESSIONAL REVIEW — this document is generated from source notes and does not constitute compliance advice or certification.";

export interface PlannedPackSection {
  requirement_id: string;
  /** Bare requirement title, no citation — used to locate the section. */
  title: string;
  /** The exact heading text instructed and later verified against. */
  heading: string;
  status: CoverageStatus;
}

export interface CompliancePackDraft {
  client_id: string;
  title: string;
  documentId: string;
  durableDocumentId: string | null;
  sessionId: string;
  plannedSections: PlannedPackSection[];
}

/**
 * Merges the model's draft outline with coverage.ts's authoritative
 * findings into the sections actually instructed. The outline supplies
 * ordering/intent; the heading text — including whether it carries a
 * citation at all — comes entirely from the coverage entry, never from the
 * model's own guess at what the evidence shows.
 */
export function buildPlannedSections(
  outline: CompliancePackOutline,
  coverageEntries: CoverageEntry[],
  requirements: Requirement[],
): PlannedPackSection[] {
  return outline.sections.map((s) => {
    const requirement = requirements.find((r) => r.id === s.requirement_id);
    const entry = coverageEntries.find(
      (e) => e.requirement_id === s.requirement_id && e.client_id === outline.client_id,
    );
    if (!requirement || !entry) {
      throw new Error(
        `buildPlannedSections: no coverage entry for ${s.requirement_id} / ${outline.client_id} — coverage must be assessed before generation`,
      );
    }
    return {
      requirement_id: s.requirement_id,
      title: requirement.title,
      heading: canonicalSectionHeading(requirement.title, entry),
      status: entry.status,
    };
  });
}

function instructionForStatus(status: CoverageStatus): string {
  switch (status) {
    case "MISSING":
      return "State plainly that no supporting evidence was found for this requirement in the source notes. Do not describe compliance activity that isn't evidenced — a short, honest paragraph naming the gap is correct.";
    case "INCONSISTENT":
      return "State plainly that the source notes conflict on this point, and name the conflict (which documents, which figures/dates). Do not resolve the conflict or pick a side — flagging it for human review is the correct output.";
    case "STALE":
      return "Summarise the evidence found, and state plainly that it is out of date against the requirement's review frequency, citing the date.";
    case "EVIDENCED":
      return "Summarise the evidence found in a short, plain-language paragraph, without overstating what it shows.";
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * One pack per client, one batched chatAsync request for every section in
 * that pack — a multi-section edit bills a single operation, so drafting
 * five sections costs the same as drafting one.
 */
export async function generateCompliancePack(
  client: SuperDocsClient,
  ledger: OpsLedger,
  clientRecord: Client,
  outline: CompliancePackOutline,
  plannedSections: PlannedPackSection[],
): Promise<CompliancePackDraft> {
  // A multi-section draft can bill more than one op — budget 2 up front
  // before spending anything, same margin the base pipeline uses.
  ledger.assertCanSpend(2);

  const sessionId = `notesforge-compliance-pack-${clientRecord.id}-${Date.now()}`;

  const sectionInstructions = plannedSections
    .map(
      (s, i) =>
        `${i + 1}. Heading (use exactly, verbatim, as an h2 — including the parenthetical if present): "${s.heading}"\n   ${instructionForStatus(s.status)}`,
    )
    .join("\n\n");

  const message = `Draft a SEBI compliance pack for client "${clientRecord.name}" (${clientRecord.id}), titled "${outline.title}".

The document MUST open with this exact sentence, verbatim, as the very first paragraph before anything else:
"${DRAFT_BANNER}"

Use proper HTML heading levels (h1 for the title, h2 for each section below). Reproduce every section heading below EXACTLY as given — do not paraphrase, shorten, reorder its words, or drop the parenthetical citation, since headings are checked verbatim afterwards.

Sections (draft ALL of these in this single turn):
${sectionInstructions}`;

  // response_mode 'compact': polled job results carry per-section
  // chunk_diffs instead of full document HTML — this is document-scale
  // generation and the whole body is never needed in context.
  const { job_id: initialJobId } = await client.chatAsync({
    message,
    session_id: sessionId,
    response_mode: "compact",
  });

  const deadline = Date.now() + CONFIG.POLL_TIMEOUT_MS;
  let jobId = initialJobId;

  for (;;) {
    if (Date.now() > deadline) {
      await client.cancelJob(jobId);
      throw new JobTimeoutError(
        `generateCompliancePack: job ${jobId} did not finish within ${CONFIG.POLL_TIMEOUT_MS}ms — cancelled`,
      );
    }

    await sleep(CONFIG.POLL_INTERVAL_MS);
    const job = await client.getJob(jobId);

    if (job.status === "pending" || job.status === "in_progress") {
      console.log(`[INFO] pack ${clientRecord.id}: job ${jobId} ${job.status} (${job.progress}%)`);
      continue;
    }

    if (job.status === "awaiting_approval") {
      if (job.metadata?.awaiting_kind === "continue_prompt") {
        console.log(`[INFO] pack ${clientRecord.id}: large-edit continue pause — resuming with a fresh budget`);
        const resumed = await client.continueChat(sessionId, jobId, true);
        jobId = resumed.job_id;
        continue;
      }
      throw new Error(`generateCompliancePack: job ${jobId} is awaiting human approval`);
    }

    if (job.status === "completed") {
      const sessionDocs = await client.listSessionDocuments(sessionId);
      const focused = sessionDocs.documents.find((d) => d.focused) ?? sessionDocs.documents[0];
      if (!focused) {
        throw new Error(
          `generateCompliancePack: job ${jobId} completed but no document is open in session ${sessionId}`,
        );
      }

      return {
        client_id: clientRecord.id,
        title: outline.title,
        documentId: focused.document_id,
        durableDocumentId: focused.durable_document_id,
        sessionId,
        plannedSections,
      };
    }

    if (job.status === "failed") {
      throw new JobFailedError(`generateCompliancePack: job ${jobId} failed: ${job.error ?? "unknown error"}`);
    }

    throw new JobCancelledError(`generateCompliancePack: job ${jobId} was cancelled`);
  }
}
