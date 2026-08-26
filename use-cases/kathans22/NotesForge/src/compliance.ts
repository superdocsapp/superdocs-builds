import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { OpsLedger } from "./budget.js";
import { SuperDocsClient } from "./client.js";
import { CONFIG } from "./config.js";
import {
  applyAmendment,
  detectAmendments,
  formatAmendmentNotice,
  loadRequirementsSnapshot,
  saveRequirementsSnapshot,
  scopeAmendment,
} from "./compliance/amend.js";
import {
  type PackManifestEntry,
  writeCoverageSnapshot,
  writeLedgerSnapshot,
  writePacksManifest,
} from "./compliance/artifacts.js";
import { assessCoverage, blockForClient, findInBlock, formatCoverageReport } from "./compliance/coverage.js";
import { buildPlannedSections, generateCompliancePack } from "./compliance/generate.js";
import { planCompliancePacks } from "./compliance/plan.js";
import {
  clientsBehind,
  currentVersion,
  DEFAULT_VERSION_STORE_PATH,
  loadVersionStore,
  recordConsent,
  recordIssue,
  registerTemplateVersion,
  saveVersionStore,
} from "./compliance/registry.js";
import { buildConsentMatrix, formatConsentMatrixTable } from "./compliance/report.js";
import { verifyCompliancePack } from "./compliance/verify.js";
import { resolveCredentials } from "./credentials.js";
import type { Client } from "./domain/clients.js";
import { loadClients } from "./domain/clients.js";
import { loadRequirements } from "./domain/requirements.js";
import { type ExportFormat, exportReport } from "./export.js";
import { Logger } from "./logger.js";
import { readNotes, summariseNotes } from "./notes.js";

const TEMPLATE_ID = "ria-advisory-agreement";
const TEMPLATES_DIR = fileURLToPath(new URL("../config/templates", import.meta.url));
const DEFAULT_CONSENT_MATRIX_PATH = fileURLToPath(new URL("../state/consent-matrix.json", import.meta.url));

function getFlagValue(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  return idx === -1 ? undefined : args[idx + 1];
}

async function listRequirements(): Promise<void> {
  const requirements = await loadRequirements();
  console.log(`${requirements.length} SEBI requirement(s) tracked:\n`);
  for (const r of requirements) {
    console.log(`${r.id}  [${r.frequency} / ${r.applies_to}]`);
    console.log(`  ${r.title}`);
    console.log(`  ${r.citation}`);
    console.log("");
  }
}

async function listClients(): Promise<void> {
  const clients = await loadClients();
  console.log(`${clients.length} advisory client(s) on file:\n`);
  for (const c of clients) {
    const aiTag = c.ai_assisted ? "AI-assisted" : "non-AI";
    const reviewTag = c.risk_profile_reviewed_on ?? "NEVER REVIEWED";
    console.log(
      `${c.id}  ${c.name} (${c.advisory_type}, agreement ${c.agreement_version}, ${aiTag}) — onboarded ${c.onboarded_on}, risk review ${reviewTag}`,
    );
  }
}

async function runCoverage(args: string[]): Promise<void> {
  const notesDir = getFlagValue(args, "--notes") ?? "./corpus/ria-compliance";
  const opsCapArg = getFlagValue(args, "--ops-cap");
  const opsCap = opsCapArg ? Number(opsCapArg) : CONFIG.OPS_CAP;
  const todayArg = getFlagValue(args, "--today");
  const today = todayArg ? new Date(todayArg) : new Date();

  const logger = new Logger();
  const creds = await resolveCredentials(logger);
  const ledger = new OpsLedger(logger, opsCap);
  const client = new SuperDocsClient(creds.api_key, logger, ledger);

  const [requirements, clients, notes] = await Promise.all([
    loadRequirements(),
    loadClients(),
    readNotes(notesDir),
  ]);

  const entries = await assessCoverage(client, ledger, requirements, clients, notes, today);

  console.log(`\n=== Coverage report (${notes.length} note file(s) from ${notesDir}) ===\n`);
  console.log(formatCoverageReport(entries, clients, requirements));

  const byStatus = { EVIDENCED: 0, STALE: 0, MISSING: 0, INCONSISTENT: 0 };
  for (const e of entries) byStatus[e.status]++;
  console.log(
    `\n${entries.length} entries — EVIDENCED ${byStatus.EVIDENCED}, STALE ${byStatus.STALE}, MISSING ${byStatus.MISSING}, INCONSISTENT ${byStatus.INCONSISTENT}`,
  );

  console.log(`\n${ledger.report()}\n`);
  console.log(`total ops charged: ${ledger.spent}`);
  console.log(`monthly remaining: ${ledger.remaining ?? "?"}`);

  await writeCoverageSnapshot(entries, notesDir);
  await writeLedgerSnapshot("coverage", ledger, opsCap);
  await logger.flush("compliance-coverage-log.json");
}

async function runGenerate(args: string[]): Promise<void> {
  const notesDir = getFlagValue(args, "--notes") ?? "./corpus/ria-compliance";
  const opsCapArg = getFlagValue(args, "--ops-cap");
  const opsCap = opsCapArg ? Number(opsCapArg) : CONFIG.OPS_CAP;
  const todayArg = getFlagValue(args, "--today");
  const today = todayArg ? new Date(todayArg) : new Date();
  const clientsArg = getFlagValue(args, "--clients");
  const selectedIds = clientsArg ? new Set(clientsArg.split(",").map((s) => s.trim())) : null;
  const outDir = getFlagValue(args, "--out") ?? "./out";
  const formats = (getFlagValue(args, "--formats") ?? "docx,pdf")
    .split(",")
    .map((f) => f.trim()) as ExportFormat[];
  const skipExport = args.includes("--no-export");

  const logger = new Logger();
  const creds = await resolveCredentials(logger);
  const ledger = new OpsLedger(logger, opsCap);
  const client = new SuperDocsClient(creds.api_key, logger, ledger);

  const [requirements, allClients, notes] = await Promise.all([
    loadRequirements(),
    loadClients(),
    readNotes(notesDir),
  ]);

  const clients: Client[] = selectedIds ? allClients.filter((c) => selectedIds.has(c.id)) : allClients;
  if (clients.length === 0) {
    throw new Error(`runGenerate: no clients matched --clients "${clientsArg}"`);
  }
  console.log(`[INFO] generating pack(s) for: ${clients.map((c) => c.id).join(", ")}`);

  logger.step("planning per-client pack outlines");
  const digest = summariseNotes(notes);
  const { outlines } = await planCompliancePacks(client, ledger, requirements, allClients, digest);

  logger.step("assessing coverage");
  const coverageEntries = await assessCoverage(client, ledger, requirements, allClients, notes, today);

  const packManifest: PackManifestEntry[] = [];

  for (const c of clients) {
    const outline = outlines.find((o) => o.client_id === c.id);
    if (!outline) {
      console.warn(`[WARN] no plan outline returned for ${c.id} — skipping`);
      continue;
    }

    const plannedSections = buildPlannedSections(outline, coverageEntries, requirements);

    logger.step(`generating pack for ${c.id} (${c.name})`);
    let draft;
    try {
      draft = await generateCompliancePack(client, ledger, c, outline, plannedSections);
    } catch (err) {
      // One client's job flaking (e.g. a session that completed without a
      // focused document) must not lose every other client's already-drafted
      // pack — log it and move on; the manifest below still records whoever
      // succeeded, and a retry with --clients can pick up just this one.
      console.warn(
        `[WARN] ${c.id}: pack generation failed — ${err instanceof Error ? err.message : String(err)} — skipping`,
      );
      continue;
    }
    console.log(`[OK] pack drafted: ${draft.durableDocumentId ?? draft.documentId}`);

    let verified = false;
    if (draft.durableDocumentId) {
      logger.step(`verifying pack for ${c.id}`);
      const result = await verifyCompliancePack(client, draft.durableDocumentId, plannedSections);
      verified = result.ok;
      if (!result.ok) {
        console.warn(`[WARN] ${c.id}: verification failed — see warnings above`);
      }
    } else {
      console.warn(`[WARN] ${c.id}: no durable document id — skipping verification`);
    }

    // requestDownloadUrl is a free read (0 ops) — exporting the pack costs
    // nothing against the run's budget, so it happens by default.
    let exportedFiles: string[] = [];
    if (!skipExport) {
      logger.step(`exporting pack for ${c.id}`);
      try {
        exportedFiles = await exportReport(client, draft.sessionId, formats, path.join(outDir, c.id));
      } catch (err) {
        console.warn(
          `[WARN] ${c.id}: export failed — ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    }

    packManifest.push({
      client_id: c.id,
      client_name: c.name,
      title: draft.title,
      documentId: draft.documentId,
      durableDocumentId: draft.durableDocumentId,
      sessionId: draft.sessionId,
      verified,
      plannedSections,
      exportedFiles,
      generated_at: new Date().toISOString(),
    });
  }

  console.log(`\n${ledger.report()}\n`);
  console.log(`total ops charged: ${ledger.spent}`);
  console.log(`monthly remaining: ${ledger.remaining ?? "?"}`);

  await writePacksManifest(packManifest);
  await writeLedgerSnapshot("generate", ledger, opsCap);
  await logger.flush("compliance-generate-log.json");
}

/**
 * Registers the two known template versions and, for every client, records
 * their historical agreement issuance and (where the corpus documents a
 * signed date) their consent — idempotent, so re-running never duplicates
 * an issuance already on file. This is the one place the registry gets
 * populated from the corpus; everything downstream (--matrix) only reads.
 */
async function runRegistrySeed(args: string[]): Promise<void> {
  const notesDir = getFlagValue(args, "--notes") ?? "./corpus/ria-compliance";

  const store = await loadVersionStore();

  const v1Content = await readFile(path.join(TEMPLATES_DIR, "ria-advisory-agreement-v1.md"), "utf8");
  const v2Content = await readFile(path.join(TEMPLATES_DIR, "ria-advisory-agreement-v2.md"), "utf8");
  registerTemplateVersion(store, TEMPLATE_ID, "v1", "2015-04-01", ["RIA-AGR-01"], v1Content);
  registerTemplateVersion(store, TEMPLATE_ID, "v2", "2023-01-01", ["RIA-AGR-01", "RIA-AI-01"], v2Content);

  const clients = await loadClients();
  const notes = await readNotes(notesDir);
  const onboardingNote = notes.find((n) => n.name === "client-onboarding-notes.md");

  let issued = 0;
  let consented = 0;

  for (const c of clients) {
    const alreadyIssued = store.client_versions.some(
      (r) => r.client_id === c.id && r.template_id === TEMPLATE_ID && r.version === c.agreement_version,
    );
    if (alreadyIssued) continue;

    recordIssue(store, c.id, TEMPLATE_ID, c.agreement_version, c.onboarded_on);
    issued++;

    const block = onboardingNote ? blockForClient(onboardingNote, c.id) : null;
    const evidence = block ? findInBlock(block, ["agreement"])[0] : undefined;
    if (evidence) {
      recordConsent(store, c.id, TEMPLATE_ID, c.agreement_version, c.onboarded_on, `${evidence.file}:${evidence.line}`);
      consented++;
    } else {
      console.warn(`[WARN] runRegistrySeed: no agreement-signing evidence found for ${c.id} — issued without consent recorded`);
    }
  }

  await saveVersionStore(store);
  console.log(`[OK] registry seeded: ${issued} new issuance(s), ${consented} consent(s) recorded`);
  console.log(`[INFO] store written to ${DEFAULT_VERSION_STORE_PATH}`);
}

async function runMatrix(): Promise<void> {
  const store = await loadVersionStore();
  const clients = await loadClients();
  const matrix = buildConsentMatrix(store, clients);

  console.log(formatConsentMatrixTable(matrix));

  const behind = clientsBehind(store, TEMPLATE_ID);
  console.log(`\n${behind.length} client(s) behind on ${TEMPLATE_ID}:`);
  for (const b of behind) {
    console.log(`  ${b.client_id}: issued ${b.version} (current: ${b.current_version}) — ${b.reason}`);
  }

  await mkdir(path.dirname(DEFAULT_CONSENT_MATRIX_PATH), { recursive: true });
  await writeFile(DEFAULT_CONSENT_MATRIX_PATH, `${JSON.stringify(matrix, null, 2)}\n`, "utf8");
  console.log(`\n[INFO] matrix written to ${DEFAULT_CONSENT_MATRIX_PATH}`);
}

function nextVersionLabel(current: string): string {
  const m = current.match(/^v(\d+)$/);
  return m ? `v${Number(m[1]) + 1}` : `${current}-amended`;
}

/**
 * Runs the full amendment pipeline: DETECT (against state's requirements
 * snapshot, bootstrapped from config/requirements.yaml if this is the
 * first run) -> SCOPE -> AMEND -> NOTIFY -> RECORD. Also runs a real
 * generateCompliancePack for the same affected clients under a second
 * ledger, purely to print a genuine ops comparison — not an estimate —
 * against what a full regeneration would have cost.
 */
async function runAmend(args: string[]): Promise<void> {
  const newRequirementsPath = getFlagValue(args, "--new-requirements") ?? "./config/requirements-v2.yaml";
  const effectiveFrom = getFlagValue(args, "--effective-from") ?? new Date().toISOString().slice(0, 10);
  const opsCapArg = getFlagValue(args, "--ops-cap");
  const opsCap = opsCapArg ? Number(opsCapArg) : CONFIG.OPS_CAP;
  const skipRegenComparison = args.includes("--no-regen-comparison");

  const logger = new Logger();
  const creds = await resolveCredentials(logger);
  const amendLedger = new OpsLedger(logger, opsCap);
  const client = new SuperDocsClient(creds.api_key, logger, amendLedger);

  logger.step("DETECT — comparing against the requirements snapshot recorded in state");
  let baseline = await loadRequirementsSnapshot();
  if (baseline === null) {
    baseline = await loadRequirements();
    console.log("[INFO] no requirements snapshot on file yet — bootstrapping it from config/requirements.yaml");
  }
  const updatedRequirements = await loadRequirements(newRequirementsPath);
  const events = detectAmendments(baseline, updatedRequirements);

  if (events.length === 0) {
    console.log("[OK] no amendment detected — the requirements register is unchanged since the last recorded snapshot");
    return;
  }
  console.log(`[INFO] ${events.length} amendment event(s) detected:`);
  for (const e of events) console.log(`  - ${e.requirement_id} (${e.kind})`);

  const store = await loadVersionStore();
  const clients = await loadClients();

  const noticesDir = path.join(fileURLToPath(new URL("../state/amendments", import.meta.url)));
  let totalNotices = 0;
  let allAffectedClientIds: string[] = [];

  for (const event of events) {
    logger.step(`SCOPE — blast radius for ${event.requirement_id}`);
    const previewScope = scopeAmendment(store, event);
    console.log(
      `[INFO] affected template(s): ${previewScope.affected_template_ids.join(", ") || "(none)"}; affected client(s): ${previewScope.affected_client_ids.join(", ") || "(none)"}`,
    );
    if (previewScope.affected_template_ids.length === 0) {
      console.log(`[INFO] no template currently references ${event.requirement_id} — nothing to amend`);
      continue;
    }

    const currentLabel = currentVersion(store, previewScope.affected_template_ids[0]!)!.version;

    logger.step(`AMEND + NOTIFY + RECORD — ${event.requirement_id}`);
    const result = await applyAmendment(
      client,
      amendLedger,
      store,
      clients,
      event,
      effectiveFrom,
      nextVersionLabel(currentLabel),
    );

    const eventDir = path.join(noticesDir, `${event.requirement_id}-${effectiveFrom}`);
    await mkdir(eventDir, { recursive: true });
    for (const notice of result.notices) {
      await writeFile(
        path.join(eventDir, `${notice.client_id}-notice.md`),
        formatAmendmentNotice(notice),
        "utf8",
      );
    }
    // The .md notice is the human-readable artifact; this structured
    // sibling is so a reader (e.g. the UI) doesn't have to parse markdown
    // back into the AmendmentNotice fields it was built from.
    await writeFile(
      path.join(eventDir, "event.json"),
      `${JSON.stringify(
        {
          requirement_id: event.requirement_id,
          kind: event.kind,
          effective_from: effectiveFrom,
          scope: result.scope,
          notices: result.notices,
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
    console.log(`[OK] ${result.notices.length} notice(s) written to ${eventDir}`);

    totalNotices += result.notices.length;
    allAffectedClientIds = allAffectedClientIds.concat(result.notices.map((n) => n.client_id));
  }

  await saveVersionStore(store);
  await saveRequirementsSnapshot(updatedRequirements);
  console.log(`[OK] state/versions.json and state/requirements-snapshot.json updated`);

  console.log(`\n${amendLedger.report()}\n`);
  console.log(`amendment ops charged: ${amendLedger.spent}`);

  if (!skipRegenComparison && allAffectedClientIds.length > 0) {
    logger.step("comparing against a real full regeneration of the same affected clients");
    const regenLedger = new OpsLedger(logger, opsCap);
    const regenClient = new SuperDocsClient(creds.api_key, logger, regenLedger);
    const requirements = await loadRequirements();
    const notes = await readNotes("./corpus/ria-compliance");
    const digest = summariseNotes(notes);
    const { outlines } = await planCompliancePacks(regenClient, regenLedger, requirements, clients, digest);
    const coverageEntries = await assessCoverage(regenClient, regenLedger, requirements, clients, notes);

    for (const clientId of allAffectedClientIds) {
      const c = clients.find((cl) => cl.id === clientId)!;
      const outline = outlines.find((o) => o.client_id === clientId);
      if (!outline) continue;
      const plannedSections = buildPlannedSections(outline, coverageEntries, requirements);
      await generateCompliancePack(regenClient, regenLedger, c, outline, plannedSections);
    }

    console.log(`\nfull-regeneration ops for the same ${allAffectedClientIds.length} client(s): ${regenLedger.spent}`);
    console.log(`\n=== ops comparison ===`);
    console.log(`amendment:         ${amendLedger.spent}`);
    console.log(`full regeneration: ${regenLedger.spent}`);
    console.log(
      amendLedger.spent < regenLedger.spent
        ? `[OK] amendment is cheaper by ${regenLedger.spent - amendLedger.spent} op(s)`
        : `[WARN] amendment was not cheaper than full regeneration this run`,
    );
  }

  await writeLedgerSnapshot("amend", amendLedger, opsCap);
  await logger.flush("compliance-amend-log.json");
}

export async function runComplianceCli(args: string[]): Promise<void> {
  if (args.includes("--list-requirements")) {
    await listRequirements();
    return;
  }

  if (args.includes("--list-clients")) {
    await listClients();
    return;
  }

  if (args.includes("--coverage")) {
    await runCoverage(args);
    return;
  }

  if (args.includes("--generate")) {
    await runGenerate(args);
    return;
  }

  if (args.includes("--registry-seed")) {
    await runRegistrySeed(args);
    return;
  }

  if (args.includes("--matrix")) {
    await runMatrix();
    return;
  }

  if (args.includes("--amend")) {
    await runAmend(args);
    return;
  }

  console.log(
    "compliance: no recognised command. Try --list-requirements, --list-clients, --coverage, --generate, --registry-seed, --matrix or --amend.",
  );
  process.exitCode = 1;
}
