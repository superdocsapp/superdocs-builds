import { CONFIG } from "./config.js";
import type { OpsLedger } from "./budget.js";
import type { SuperDocsClient } from "./client.js";
import { repairMissingSections, verifyStructure } from "./verify.js";

export class PlanParseError extends Error {
  constructor(
    message: string,
    public readonly rawResponse: string,
  ) {
    super(message);
    this.name = "PlanParseError";
  }
}

export interface ReportSection {
  heading: string;
  intent: string;
  source_notes: string[];
}

export interface ReportPlan {
  title: string;
  sections: ReportSection[];
}

export interface PlanReportResult {
  plan: ReportPlan;
  sessionId: string;
}

function stripJsonFences(text: string): string {
  const trimmed = text.trim();
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return fenced ? fenced[1]!.trim() : trimmed;
}

export async function planReport(
  client: SuperDocsClient,
  ledger: OpsLedger,
  notesDigest: string,
  title?: string,
): Promise<PlanReportResult> {
  const sessionId = `notesforge-${Date.now()}`;

  // Planning is a single chat() call — budget for 1 op before spending it.
  ledger.assertCanSpend(1);

  const titleInstruction = title
    ? `The report title must be exactly "${title}".`
    : "Choose a concise, descriptive title.";

  const message = `You are planning the structure of a report built from a folder of rough notes.
${titleInstruction}

Respond with JSON only — no prose, no commentary, no markdown code fences. The JSON must match exactly this shape:
{"title": string, "sections": [{"heading": string, "intent": string, "source_notes": string[]}]}

- "intent" is a one-sentence description of what that section should cover.
- "source_notes" lists which of the digest's "### <filename>" headings that section draws from.

Notes digest:
${notesDigest}`;

  // model_tier 'core': planning only has to read the digest and structure an
  // outline, not draft finished prose — 'core' (fast, default) is accurate
  // enough for that. Prompt 8's actual drafting is the heavier task.
  const response = await client.chat({
    message,
    session_id: sessionId,
    model_tier: "core",
  });

  const cleaned = stripJsonFences(response.response);
  let plan: ReportPlan;
  try {
    plan = JSON.parse(cleaned) as ReportPlan;
  } catch {
    console.error(`[ERROR] planReport: AI response was not valid JSON:\n${response.response}`);
    throw new PlanParseError("planReport: AI response was not valid JSON", response.response);
  }

  return { plan, sessionId };
}

export class JobFailedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JobFailedError";
  }
}

export class JobCancelledError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JobCancelledError";
  }
}

export class JobTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "JobTimeoutError";
  }
}

export interface GenerateReportResult {
  documentId: string;
  durableDocumentId: string | null;
  sessionId: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function generateReport(
  client: SuperDocsClient,
  ledger: OpsLedger,
  sessionId: string,
  plan: ReportPlan,
  notesDigest: string,
): Promise<GenerateReportResult> {
  // A full multi-section draft can bill more than one op (roughly one per
  // ~25 sections edited) — budget 2 up front before spending anything.
  ledger.assertCanSpend(2);

  const outline = plan.sections
    .map((s, i) => `${i + 1}. ${s.heading} — ${s.intent}`)
    .join("\n");

  const message = `Draft the full report "${plan.title}" from the approved outline below, using the notes digest as source material.

Use proper HTML heading levels (h1 for the title, h2 for each top-level section) and write complete prose for every section — do not just restate the outline as bullet points.

Approved outline:
${outline}

Notes digest:
${notesDigest}`;

  // response_mode 'compact': polled job results carry per-section
  // chunk_diffs instead of the full document HTML, since this is a
  // document-scale generation and we don't need the whole body in context.
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
        `generateReport: job ${jobId} did not finish within ${CONFIG.POLL_TIMEOUT_MS}ms — cancelled`,
      );
    }

    await sleep(CONFIG.POLL_INTERVAL_MS);
    const job = await client.getJob(jobId);

    if (job.status === "pending" || job.status === "in_progress") {
      console.log(`[INFO] job ${jobId}: ${job.status} (${job.progress}%)`);
      continue;
    }

    if (job.status === "awaiting_approval") {
      if (job.metadata?.awaiting_kind === "continue_prompt") {
        console.log(`[INFO] job ${jobId}: large-edit continue pause — resuming with a fresh budget`);
        const resumed = await client.continueChat(sessionId, jobId, true);
        jobId = resumed.job_id;
        continue;
      }
      console.warn(
        `[WARN] job ${jobId}: awaiting human approval (${job.metadata?.pending_changes?.length ?? 0} pending change(s)) — this is a HITL pause the CLI cannot resolve on its own`,
      );
      throw new Error(`generateReport: job ${jobId} is awaiting human approval`);
    }

    if (job.status === "completed") {
      // The job result doesn't carry document ids directly — resolve them
      // from the session's open documents instead.
      const sessionDocs = await client.listSessionDocuments(sessionId);
      const focused =
        sessionDocs.documents.find((d) => d.focused) ?? sessionDocs.documents[0];
      if (!focused) {
        throw new Error(
          `generateReport: job ${jobId} completed but no document is open in session ${sessionId}`,
        );
      }

      // Verify the draft actually contains every planned section — via the
      // free structure read, never by exporting. GET /v1/documents/{id}
      // takes the durable id, not the session-local slot id.
      if (focused.durable_document_id) {
        const check = await verifyStructure(client, focused.durable_document_id, plan);
        if (!check.ok) {
          await repairMissingSections(client, ledger, sessionId, check.missing);
          const recheck = await verifyStructure(client, focused.durable_document_id, plan);
          if (recheck.ok) {
            console.log("[OK] repair succeeded — all planned sections now present");
          } else {
            console.warn(
              `[WARN] repair attempted once; ${recheck.missing.length} section(s) still missing: ${recheck.missing.join(", ")} — reporting honestly rather than retrying further`,
            );
          }
        }
      } else {
        console.warn(
          `[WARN] generateReport: document has no durable id yet — skipping structure verification`,
        );
      }

      return {
        documentId: focused.document_id,
        durableDocumentId: focused.durable_document_id,
        sessionId,
      };
    }

    if (job.status === "failed") {
      throw new JobFailedError(`generateReport: job ${jobId} failed: ${job.error ?? "unknown error"}`);
    }

    throw new JobCancelledError(`generateReport: job ${jobId} was cancelled`);
  }
}

export interface FinishReportOptions {
  title: string;
  pageBreaks?: boolean;
  footer?: boolean;
}

/**
 * One batched chat request for every finishing touch. finishReport doesn't
 * receive documentId/plan, so unlike verifyStructure this compares raw
 * section/block counts before and after via the same free structure read,
 * rather than a full plan-vs-heading diff.
 */
export async function finishReport(
  client: SuperDocsClient,
  ledger: OpsLedger,
  sessionId: string,
  opts: FinishReportOptions,
): Promise<void> {
  ledger.assertCanSpend(1);

  const sessionDocs = await client.listSessionDocuments(sessionId);
  const focused = sessionDocs.documents.find((d) => d.focused) ?? sessionDocs.documents[0];
  const durableId = focused?.durable_document_id ?? null;
  const before = durableId ? await client.getDocument(durableId) : null;

  const instructions: string[] = [
    "Add a table of contents at the top of the document (it renders live from the headings, both in the editor and in every export format).",
  ];
  if (opts.pageBreaks) {
    instructions.push("Insert a page break immediately before each top-level (h2) section.");
  }
  if (opts.footer) {
    instructions.push(`Add a footer showing the document title ("${opts.title}") and the page number.`);
  }
  instructions.push(
    "Tighten the prose in any section that still reads like raw notes rather than a finished report.",
  );

  // One batched request for every finishing touch — a multi-section edit in
  // a single chat call bills one operation; four separate requests for the
  // same four touches would bill four.
  await client.chat({
    message: `Apply all of the following finishing touches to the document in this single turn:\n${instructions
      .map((i) => `- ${i}`)
      .join("\n")}`,
    session_id: sessionId,
  });

  if (durableId && before) {
    const after = await client.getDocument(durableId);
    console.log(
      `[INFO] finishing pass effect — sections: ${before.structure.section_count} -> ${after.structure.section_count}, blocks: ${before.structure.block_count} -> ${after.structure.block_count}`,
    );
  } else {
    console.warn(
      "[WARN] finishReport: no durable document id available — skipping before/after structure comparison",
    );
  }
}
