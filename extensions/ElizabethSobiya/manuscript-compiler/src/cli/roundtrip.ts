/**
 * The four-call contract, end to end, drivable by a machine.
 *
 *   upload  →  chat (review mode)  →  approve, item by item  →  export
 *
 * This exists for two reasons. The first is verification: it is one command that
 * proves the integration works against the live API rather than against a fake.
 * The second is that the approval gate has to be an *operation*, not a button —
 * something another program can call — and the only way to show that is to have a
 * program call it.
 *
 * The decision is still explicit. `--approve` and `--reject` are choices the
 * caller makes; there is no default and nothing is approved by omission.
 */

import { compile } from "../core/compile";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions } from "../core/types";
import { FsVault } from "../vault/fs-vault";
import { SuperDocsClient, SuperDocsError, type ProposedChange } from "../superdocs/client";
import { nodeTransport } from "../superdocs/node-transport";
import { pollJob } from "../superdocs/jobs";
import { uploadFigures } from "../superdocs/figures";
import { buildInstruction } from "../core/injection";
import { hash } from "../core/util";

export interface RoundtripArgs {
  vaultRoot: string;
  spine: string;
  instruction: string;
  /** "approve-all" | "reject-all" | "approve-first" — an explicit decision policy. */
  decision: "approve-all" | "reject-all" | "approve-first";
  outDir: string;
  apiKey: string;
  log: (line: string) => void;
}

export interface RoundtripReport {
  ok: boolean;
  sessionId: string;
  jobId: string | null;
  proposed: number;
  approved: number;
  rejected: number;
  operationsCharged: number;
  operationsRemaining: number | null;
  exports: Array<{ format: string; path: string; bytes: number; warnings: number }>;
  steps: Array<{ step: string; ms: number; detail?: string }>;
}

export async function roundtrip(
  args: RoundtripArgs,
  io: {
    writeFile: (path: string, data: Uint8Array | string) => Promise<void>;
    join: (...parts: string[]) => string;
  },
): Promise<RoundtripReport> {
  const steps: RoundtripReport["steps"] = [];
  const time = async <T>(step: string, fn: () => Promise<T>, detail?: string): Promise<T> => {
    const t0 = Date.now();
    try {
      return await fn();
    } finally {
      steps.push({ step, ms: Date.now() - t0, ...(detail ? { detail } : {}) });
    }
  };

  let charged = 0;
  const client = new SuperDocsClient({
    apiKey: args.apiKey,
    transport: nodeTransport,
    onUsage: (u) => {
      charged += u.ops_charged ?? 0;
    },
  });

  // Read the account before and after. The per-response `usage` block is the fast
  // path, but an async job does not always carry one, and a spend figure that is
  // sometimes silently zero is worse than no figure at all.
  const quotaBefore = await time("quota", async () => {
    try {
      return (await client.accountStatus()).quota?.remaining ?? null;
    } catch {
      return null;
    }
  });

  const options: CompileOptions = { ...DEFAULT_COMPILE_OPTIONS, spinePath: args.spine };
  const vault = new FsVault(args.vaultRoot);

  // --- 0. compile (local, free) ---------------------------------------------
  const compiled = await time("compile", () => compile({ vault, options, manifestJson: null }));
  args.log(
    `compile      ${compiled.stats.chapters} chapters, ${compiled.stats.words.toLocaleString()} words, ` +
      `${compiled.diagnostics.filter((d) => d.severity === "error").length} errors`,
  );

  const figures = await time("upload-figures", () =>
    uploadFigures({
      html: compiled.html,
      figures: compiled.assignedFigures,
      vault,
      client,
      cache: compiled.manifest.imageUrls,
    }),
  );
  args.log(`figures      ${figures.uploaded} uploaded, ${figures.reused} reused from cache`);

  // A fresh session per run. Reusing one means a second round trip can collide with
  // the first turn still finishing, and the API rightly answers 409 rather than
  // interleaving two conversations. Two runs at once stay two runs.
  const sessionId = `manuscript-roundtrip-${hash(compiled.meta.title)}-${Date.now().toString(36)}`;

  // --- 1. upload -------------------------------------------------------------
  await time("upload", () =>
    client.uploadDocument({
      sessionId,
      filename: `${slug(compiled.meta.title)}.html`,
      content: figures.html,
      contentType: "text/html",
    }),
  );
  args.log(`upload       manuscript is the active document in session ${sessionId}`);

  // --- 2. chat, in review mode ------------------------------------------------
  const { job_id } = await time("chat", () =>
    client.chatAsync({
      sessionId,
      message: buildInstruction(args.instruction),
      approvalMode: "ask_every_time",
    }),
  );
  args.log(`chat         job ${job_id} started in review mode`);

  const outcome = await time("poll", () =>
    pollJob(client, job_id, {
      onTick: (job, elapsed) => {
        if (elapsed > 0 && elapsed % 30_000 < 2100) {
          args.log(`             still ${job.status} after ${Math.round(elapsed / 1000)}s`);
        }
      },
    }),
  );

  let proposed: ProposedChange[] = [];
  let approved = 0;
  let rejected = 0;

  if (outcome.kind === "awaiting_approval") {
    proposed = outcome.changes;
    args.log(`review       ${proposed.length} change(s) proposed; policy is "${args.decision}"`);

    // --- 3. approve, item by item -------------------------------------------
    const decisions = proposed.map((change, i) => ({
      changeId: change.change_id,
      approved:
        args.decision === "approve-all" ? true : args.decision === "reject-all" ? false : i === 0,
      ...(args.decision === "reject-all"
        ? { feedback: "Rejected by the round-trip policy, to prove a rejection is respected." }
        : {}),
    }));
    approved = decisions.filter((d) => d.approved).length;
    rejected = decisions.length - approved;

    await time("approve", () => client.approve({ sessionId, jobId: job_id, decisions }));
    args.log(`approve      ${approved} approved, ${rejected} rejected — each decided explicitly`);

    // Let the job settle after the decisions before exporting.
    await time("settle", async () => {
      await pollJob(client, job_id, { timeoutMs: 5 * 60_000 });
    });
  } else if (outcome.kind === "completed") {
    args.log("review       nothing was proposed; the document already satisfied the instruction");
  } else {
    args.log(`review       job ended as "${outcome.kind}" — nothing was applied`);
  }

  // --- 4. export --------------------------------------------------------------
  const exports: RoundtripReport["exports"] = [];
  for (const format of ["pdf", "docx"] as const) {
    const result = await time(`export-${format}`, () =>
      client.exportDocument({
        format,
        sessionId,
        options: { paper_size: "A4", filename: slug(compiled.meta.title) },
      }),
    );
    const path = io.join(args.outDir, `roundtrip-${slug(compiled.meta.title)}.${format}`);
    await io.writeFile(path, new Uint8Array(result.bytes));

    // A success line only ever means the file is genuinely there with bytes in it.
    const bytes = result.bytes.byteLength;
    if (bytes <= 0) throw new Error(`${format} export returned an empty body; nothing was written.`);
    exports.push({ format, path, bytes, warnings: result.warnings.length });
    args.log(
      `export       ${path} (${(bytes / 1024).toFixed(0)} KB` +
        (result.warnings.length ? `, ${result.warnings.length} warning(s)` : "") +
        ")",
    );
  }

  let quotaAfter: number | null = null;
  try {
    quotaAfter = (await client.accountStatus()).quota?.remaining ?? null;
  } catch {
    quotaAfter = null;
  }
  const spent =
    quotaBefore !== null && quotaAfter !== null ? quotaBefore - quotaAfter : charged;
  args.log(
    `operations   ${spent} charged for the whole round trip` +
      (quotaAfter !== null ? ` · ${quotaAfter} remaining this month` : ""),
  );

  return {
    ok: exports.length === 2,
    sessionId,
    jobId: job_id,
    proposed: proposed.length,
    approved,
    rejected,
    operationsCharged: spent,
    operationsRemaining: quotaAfter,
    exports,
    steps,
  };
}

export function isSuperDocsError(err: unknown): err is SuperDocsError {
  return err instanceof SuperDocsError;
}

function slug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "manuscript"
  );
}
