import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { buildDraftInstruction } from "../lib/buildInstruction";
import { runDeterministicAudit } from "../lib/calibration/deterministicAudit";
import { runVerifier, readVerifierConfig } from "../lib/calibration/verifier";
import { textFromHtml } from "../lib/textFromHtml";
import { renderReport, summarise, type EvalRun } from "./score";
import type { Intake, StrengthBand } from "../lib/types";

/**
 * The calibration eval.
 *
 * Every design choice here comes from one line in the brief: budget your
 * operations, give anything that runs in a loop a small-sample mode and a
 * stopping rule, and learn that on day one rather than day nine.
 *
 *   --n <k>          letters per band (default 1, so the default run is cheap)
 *   --max-ops <k>    hard ceiling on SuperDocs operations. The run stops when
 *                    it would exceed this, mid-way, and reports what it did.
 *   --arms both      run baseline and audited arms for the ablation
 *   --resume         continue from an interrupted run instead of restarting
 *   --dry-run        no network at all: prints the plan and the cost
 *
 * Results are appended to runs.jsonl after EVERY letter, not at the end. A run
 * killed at letter seven keeps seven letters. Checkpointing after the expensive
 * part is the whole point; batching the writes to be tidy would throw away the
 * money already spent.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS_DIR = join(HERE, "results");
const RUNS_PATH = join(RESULTS_DIR, "runs.jsonl");
const REPORT_PATH = join(RESULTS_DIR, "latest.md");

interface Args {
  n: number;
  maxOps: number;
  arms: ("baseline" | "audited")[];
  resume: boolean;
  dryRun: boolean;
}

function parseArgs(argv: string[]): Args {
  const get = (flag: string): string | undefined => {
    const i = argv.indexOf(flag);
    return i === -1 ? undefined : argv[i + 1];
  };

  const armsArg = get("--arms") ?? "both";
  return {
    n: Math.max(1, Number(get("--n") ?? 1)),
    maxOps: Math.max(1, Number(get("--max-ops") ?? 20)),
    arms:
      armsArg === "baseline" ? ["baseline"] : armsArg === "audited" ? ["audited"] : ["baseline", "audited"],
    resume: argv.includes("--resume"),
    dryRun: argv.includes("--dry-run"),
  };
}

interface Fixture extends Omit<Intake, "evidence"> {
  id: string;
  evidence: { claim: string; evidence: string }[];
}

function loadFixtures(): Fixture[] {
  const raw = JSON.parse(readFileSync(join(HERE, "fixtures", "intakes.json"), "utf-8"));
  return raw.cases as Fixture[];
}

function toIntake(fixture: Fixture): Intake {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- destructured only to drop `id` from the rest
  const { id, ...rest } = fixture;
  return rest as Intake;
}

const API_BASE = process.env.SUPERDOCS_BASE_URL?.replace(/\/$/, "") ?? "https://api.superdocs.app/v1";

async function superdocs<T>(path: string, init: RequestInit & { timeoutMs?: number }): Promise<T> {
  const key = process.env.SUPERDOCS_API_KEY;
  if (!key) throw new Error("SUPERDOCS_API_KEY is not set.");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), init.timeoutMs ?? 60_000);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { Authorization: `Bearer ${key}`, ...(init.headers ?? {}) },
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`${path} -> ${res.status}: ${text.slice(0, 300)}`);
    return JSON.parse(text) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** One letter, drafted through SuperDocs, auto-approved so the eval can read it. */
async function draftLetter(intake: Intake): Promise<string> {
  const sessionId = `eval-${crypto.randomUUID()}`;

  const form = new FormData();
  form.append("file", new Blob(["<h1>Reference Letter</h1><p>[placeholder]</p>"], { type: "text/html" }), "starter.html");
  form.append("session_id", sessionId);
  await superdocs("/documents/upload", { method: "POST", body: form });

  const job = await superdocs<{ job_id: string }>("/chat/async", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: buildDraftInstruction(intake),
      session_id: sessionId,
      // The eval measures what the drafter produces, so it approves everything.
      // The product does not: a human gates every change there.
      approval_mode: "auto",
    }),
  });

  // Poll. Operations on large documents legitimately run for minutes.
  const deadline = Date.now() + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3000));
    const status = await superdocs<{
      status: string;
      error?: string;
      result?: { document_changes?: { updated_html?: string } };
    }>(`/jobs/${job.job_id}`, { method: "GET", timeoutMs: 20_000 });

    if (status.status === "completed") {
      return status.result?.document_changes?.updated_html ?? "";
    }
    if (status.status === "failed" || status.status === "cancelled") {
      throw new Error(`job ${status.status}: ${status.error ?? "no reason given"}`);
    }
  }
  throw new Error("job did not finish within 6 minutes");
}

function loadCompleted(): Set<string> {
  if (!existsSync(RUNS_PATH)) return new Set();
  const done = new Set<string>();
  for (const line of readFileSync(RUNS_PATH, "utf-8").split("\n")) {
    if (!line.trim()) continue;
    try {
      const run = JSON.parse(line) as EvalRun & { replicate?: number };
      done.add(`${run.arm}:${run.caseId}:${run.replicate ?? 0}`);
    } catch {
      // A torn final line from a kill mid-write. Skip it and carry on.
    }
  }
  return done;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const fixtures = loadFixtures();
  mkdirSync(RESULTS_DIR, { recursive: true });

  const plan: { fixture: Fixture; arm: "baseline" | "audited"; replicate: number }[] = [];
  for (const arm of args.arms) {
    for (let replicate = 0; replicate < args.n; replicate++) {
      for (const fixture of fixtures) plan.push({ fixture, arm, replicate });
    }
  }

  const completed = args.resume ? loadCompleted() : new Set<string>();
  const todo = plan.filter((item) => !completed.has(`${item.arm}:${item.fixture.id}:${item.replicate}`));

  console.log(`Planned: ${plan.length} letters (${fixtures.length} fixtures x ${args.n} x ${args.arms.length} arms)`);
  console.log(`Already done: ${completed.size}. To run: ${todo.length}.`);
  console.log(`Operation ceiling: ${args.maxOps}. Each letter costs about 1 SuperDocs operation.`);

  if (args.dryRun) {
    console.log("\n--dry-run: nothing was sent. Drop the flag to run for real.");
    return;
  }

  if (todo.length > args.maxOps) {
    console.log(
      `\nThe plan needs ${todo.length} operations but the ceiling is ${args.maxOps}. ` +
        `Running the first ${args.maxOps} and stopping. Re-run with --resume to continue.`,
    );
  }

  const verifierConfig = readVerifierConfig();
  if (!verifierConfig) {
    console.error(
      "\nNo verifier is configured, so band inference cannot run and this eval would measure nothing.\n" +
        "Set SUPERDOCS_API_KEY. See README.",
    );
    process.exit(1);
  }

  const startedAt = new Date().toISOString();
  const notes: string[] = [];
  let spent = 0;

  for (const item of todo) {
    if (spent >= args.maxOps) {
      notes.push(`Stopped at the ${args.maxOps}-operation ceiling with ${todo.length - spent} letters unrun.`);
      console.log(`\nStopping rule hit at ${spent} operations.`);
      break;
    }

    const intake = toIntake(item.fixture);
    const started = Date.now();
    let record: EvalRun & { replicate: number };

    try {
      const html = await draftLetter(intake);
      spent++;
      const text = textFromHtml(html);

      const lexicon = runDeterministicAudit({
        text,
        band: intake.strengthBand,
        reservations: intake.reservations,
      });

      const verdict = await runVerifier({
        letterText: text,
        evidence: intake.evidence,
        declaredBand: intake.strengthBand,
        config: verifierConfig,
      });

      record = {
        caseId: item.fixture.id,
        declaredBand: intake.strengthBand as StrengthBand,
        inferredBand: verdict.inferredBand ?? null,
        lexiconFindings: lexicon.length,
        arm: item.arm,
        letterChars: text.length,
        ms: Date.now() - started,
        replicate: item.replicate,
      };

      const drift = record.inferredBand
        ? ` drift ${verdict.inferredBand === intake.strengthBand ? "0" : "!=0"}`
        : " (no band inferred)";
      console.log(
        `  ${item.arm}/${item.fixture.id}#${item.replicate}: declared ${intake.strengthBand}, ` +
          `read as ${record.inferredBand ?? "unknown"}, ${lexicon.length} lexicon findings${drift}`,
      );
    } catch (err) {
      // One bad letter must not lose the ones already paid for.
      record = {
        caseId: item.fixture.id,
        declaredBand: intake.strengthBand as StrengthBand,
        inferredBand: null,
        lexiconFindings: 0,
        arm: item.arm,
        letterChars: 0,
        ms: Date.now() - started,
        error: err instanceof Error ? err.message : String(err),
        replicate: item.replicate,
      };
      console.error(`  ${item.arm}/${item.fixture.id}#${item.replicate}: FAILED - ${record.error}`);
    }

    // Checkpoint immediately, always.
    appendFileSync(RUNS_PATH, JSON.stringify(record) + "\n", "utf-8");
  }

  const allRuns: EvalRun[] = readFileSync(RUNS_PATH, "utf-8")
    .split("\n")
    .filter((line) => line.trim())
    .flatMap((line) => {
      try {
        return [JSON.parse(line) as EvalRun];
      } catch {
        return [];
      }
    });

  writeFileSync(
    REPORT_PATH,
    renderReport({
      runs: allRuns,
      startedAt,
      model: "SuperDocs default tier",
      verifierModel: "SuperDocs (second, blind chat pass)",
      operationsSpent: spent,
      notes,
    }),
    "utf-8",
  );

  for (const arm of args.arms) {
    const summary = summarise(allRuns, arm);
    if (summary.scored === 0) continue;
    console.log(
      `\n${arm}: exact ${(summary.exactMatchRate * 100).toFixed(1)}%, ` +
        `mean drift ${summary.meanDrift >= 0 ? "+" : ""}${summary.meanDrift} ` +
        `(sd ${summary.driftStdDev}), severe inflations ${summary.severeInflationCount}`,
    );
  }
  console.log(`\nReport: ${REPORT_PATH}\nRaw: ${RUNS_PATH}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
