import { OpsLedger } from "./budget.js";
import { SuperDocsClient } from "./client.js";
import { runComplianceCli } from "./compliance.js";
import { CONFIG } from "./config.js";
import { resolveCredentials } from "./credentials.js";
import { type ExportFormat, exportReport } from "./export.js";
import { handoffAccount } from "./handoff.js";
import { Logger } from "./logger.js";
import { readNotes, summariseNotes, planUploadStrategy } from "./notes.js";
import { finishReport, generateReport, planReport } from "./pipeline.js";

function getFlagValue(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  return idx === -1 ? undefined : args[idx + 1];
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const logger = new Logger();

  if (args[0] === "compliance") {
    await runComplianceCli(args.slice(1));
    return;
  }

  if (args.includes("--whoami")) {
    const creds = await resolveCredentials(logger);
    console.log(`slug: ${creds.slug}`);
    console.log(`tier: ${creds.quota.tier}`);
    console.log(`ops remaining: ${creds.quota.remaining}`);
    return;
  }

  if (args.includes("--budget")) {
    const creds = await resolveCredentials(logger);
    const ledger = new OpsLedger(logger);
    const client = new SuperDocsClient(creds.api_key, logger, ledger);
    await client.whoami();
    console.log(ledger.report());
    return;
  }

  const handoffEmail = getFlagValue(args, "--handoff");
  if (handoffEmail) {
    const creds = await resolveCredentials(logger);
    const client = new SuperDocsClient(creds.api_key, logger, null);
    await handoffAccount(
      client,
      logger,
      handoffEmail,
      `the NotesForge CLI in ${process.cwd()}`,
    );
    return;
  }

  const notesDir = getFlagValue(args, "--notes") ?? "./sample-notes";
  const title = getFlagValue(args, "--title");
  const outDir = getFlagValue(args, "--out") ?? "./out";
  const formats = (getFlagValue(args, "--formats") ?? "docx,pdf")
    .split(",")
    .map((f) => f.trim()) as ExportFormat[];
  const pageBreaks = !args.includes("--no-page-breaks");
  const opsCapArg = getFlagValue(args, "--ops-cap");
  const opsCap = opsCapArg ? Number(opsCapArg) : CONFIG.OPS_CAP;

  if (args.includes("--plan-only")) {
    const creds = await resolveCredentials(logger);
    const ledger = new OpsLedger(logger, opsCap);
    const client = new SuperDocsClient(creds.api_key, logger, ledger);

    const notes = await readNotes(notesDir);
    const digest = summariseNotes(notes);
    planUploadStrategy(notes);

    const { plan, sessionId } = await planReport(client, ledger, digest, title);
    console.log(`session: ${sessionId}`);
    console.log(JSON.stringify(plan, null, 2));
    console.log(ledger.report());
    return;
  }

  // Full pipeline: plan -> create -> (verify+repair, inside generateReport)
  // -> finish -> export.
  const startedAt = Date.now();

  const creds = await resolveCredentials(logger);
  const ledger = new OpsLedger(logger, opsCap);
  const client = new SuperDocsClient(creds.api_key, logger, ledger);

  const notes = await readNotes(notesDir);
  const digest = summariseNotes(notes);
  planUploadStrategy(notes);

  logger.step("planning report outline");
  const { plan, sessionId } = await planReport(client, ledger, digest, title);
  logger.success(`plan: "${plan.title}" (${plan.sections.length} section(s))`);

  logger.step("generating report document");
  const generated = await generateReport(client, ledger, sessionId, plan, digest);
  logger.success(`document created: ${generated.durableDocumentId ?? generated.documentId}`);

  logger.step("applying finishing touches");
  await finishReport(client, ledger, sessionId, {
    title: plan.title,
    pageBreaks,
    footer: true,
  });

  logger.step(`exporting to ${formats.join(", ")}`);
  const outputPaths = await exportReport(client, sessionId, formats, outDir);

  let sectionCount: number | null = null;
  let blockCount: number | null = null;
  if (generated.durableDocumentId) {
    const detail = await client.getDocument(generated.durableDocumentId);
    sectionCount = detail.structure.section_count;
    blockCount = detail.structure.block_count;
  }

  const durationSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);

  console.log("\n=== Run report ===");
  console.log(`documents created: 1 (${generated.durableDocumentId ?? generated.documentId})`);
  console.log(`sections: ${sectionCount ?? "?"}`);
  console.log(`blocks: ${blockCount ?? "?"}`);
  console.log(`\n${ledger.report()}\n`);
  console.log(`total ops charged: ${ledger.spent}`);
  console.log(`monthly remaining: ${ledger.remaining ?? "?"}`);
  console.log("output files:");
  for (const p of outputPaths) console.log(`  - ${p}`);
  console.log(`duration: ${durationSeconds}s`);

  await logger.flush();
}

main()
  .then(() => {
    process.exitCode = 0;
  })
  .catch((err: unknown) => {
    console.error(`[ERROR] ${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
  });
