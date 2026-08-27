import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { loadConfig } from "../server/config.js";
import { TokenScopeError } from "../server/errors.js";
import { measureWholeDocument, rewriteSelection } from "../server/rewrite.js";
import { whoami } from "../server/superdocs.js";
import { resolveSelection } from "../shared/selection.js";
import { countTextTokens, documentText, estimateWholeDocumentTokens } from "../shared/tokens.js";
import {
  BENCHMARK_SIZES,
  INSTRUCTION,
  TARGET_PARAGRAPH,
  buildDocument,
  wordCount
} from "../shared/corpus.js";
import { RESULTS_PATH, renderReport, type BenchmarkFile, type BenchmarkRow } from "./report.js";

/**
 * The benchmark.
 *
 * For each document size it runs two real SuperDocs jobs on the same document:
 *
 *   1. the surgical edit  - rewrite one paragraph, leave the rest alone
 *   2. the counterfactual - regenerate the whole document with the same change
 *
 * and records what SuperDocs said each one cost. Both numbers are measured the
 * same way, by the same field, on the same day, against the same document. No
 * number in the output table is typed by hand.
 *
 *   npm run bench                 all five sizes
 *   npm run bench -- 3 10         only those sizes
 *   npm run bench -- --skip-whole surgical side only (half the quota, half the wait)
 *
 * Results are merged into bench/results.json, so a size that failed or was
 * skipped can be re-run on its own without discarding the rest.
 */

function parseArgs(argv: string[]): { sizes: number[]; skipWhole: boolean } {
  const skipWhole = argv.includes("--skip-whole");
  const requested = argv.filter((a) => /^\d+$/u.test(a)).map(Number);

  return { sizes: requested.length > 0 ? requested : [...BENCHMARK_SIZES], skipWhole };
}

function readExisting(): BenchmarkFile | null {
  try {
    return JSON.parse(readFileSync(RESULTS_PATH, "utf8")) as BenchmarkFile;
  } catch {
    return null;
  }
}

/**
 * A failure worth recording says why.
 *
 * TokenScopeError carries the upstream detail on `hint` - for a failed job that
 * is SuperDocs' own explanation - and a results file that drops it leaves the
 * reader with "it failed" and nothing to act on.
 */
function describe(error: unknown): string {
  if (error instanceof TokenScopeError) {
    return error.hint === undefined ? error.message : `${error.message} ${error.hint}`;
  }

  return error instanceof Error ? error.message : String(error);
}

/**
 * How long a single job may take before the benchmark gives up on it.
 *
 * Far longer than the task pane allows, because a large regeneration is measured
 * in tens of minutes and that duration is itself part of the result. An hour is
 * long enough that a run which hits it has stalled rather than merely been slow:
 * 300-page regenerations were observed frozen at 99% with `updated_at` not moving
 * for over half an hour, while the surgical edit on the same document finished in
 * under four minutes.
 */
const JOB_TIMEOUT_MS = 60 * 60 * 1000;

function fmt(value: number | null): string {
  return value === null ? "not reported" : value.toLocaleString("en-US");
}

function stamp(): string {
  return new Date().toISOString().replace(/\.\d+Z$/u, "Z");
}

async function main(): Promise<void> {
  const config = loadConfig();
  const { sizes, skipWhole } = parseArgs(process.argv.slice(2));

  if (!config.configured) {
    console.error("SUPERDOCS_API_KEY is not set. The benchmark measures the live API and");
    console.error("has no offline mode. Copy .env.example to .env.local and add your key.");
    process.exit(1);
  }

  const account = await whoami();
  const quota = account.quota;
  const needed = sizes.length * (skipWhole ? 1 : 2);

  console.log(`TokenScope benchmark  ${stamp()}`);
  console.log(`  model tier    ${config.modelTier}`);
  console.log(`  sizes         ${sizes.join(", ")} pages`);
  console.log(`  operations    ~${needed} (quota remaining: ${quota?.remaining ?? "unknown"})`);
  console.log("");

  if (quota !== undefined && quota.remaining < needed) {
    console.error(`Not enough quota: ${needed} operations needed, ${quota.remaining} left.`);
    process.exit(1);
  }

  const existing = readExisting();
  const rows = new Map<number, BenchmarkRow>((existing?.rows ?? []).map((r) => [r.pages, r]));

  for (const pages of sizes) {
    const document = buildDocument(pages);
    const selection = resolveSelection(document, TARGET_PARAGRAPH);
    const docTokens = countTextTokens(documentText(document));
    const selTokens = countTextTokens(selection.text);

    console.log(
      `--- ${pages} pages  (${wordCount(document).toLocaleString("en-US")} words, ` +
        `${docTokens.toLocaleString("en-US")} text tokens)`
    );

    const row: BenchmarkRow = {
      pages,
      words: wordCount(document),
      documentTextTokens: docTokens,
      selectionTextTokens: selTokens,
      surgical: null,
      wholeDocument: null,
      estimatedWholeDocument: null,
      measuredAt: stamp()
    };

    try {
      const t0 = Date.now();
      const result = await rewriteSelection({
        document,
        selection,
        instruction: INSTRUCTION,
        timeoutMs: JOB_TIMEOUT_MS,
        onProgress: (progress, status) =>
          process.stdout.write(`\r  surgical  ${status} ${progress}%   `)
      });
      process.stdout.write("\r");

      row.surgical = {
        reportedTokens: result.measurement.reported.surgical?.tokens ?? null,
        writtenTokens: result.work.output.tokens,
        sectionsChanged: result.work.sectionsChanged,
        elapsedMs: Date.now() - t0,
        jobId: result.jobId,
        changesInScope: result.scope.inScope.length,
        changesOutOfScope: result.scope.outOfScope.length
      };

      row.estimatedWholeDocument =
        row.surgical.reportedTokens === null
          ? null
          : estimateWholeDocumentTokens(row.surgical.reportedTokens, docTokens, selTokens).tokens;

      console.log(
        `  surgical         wrote ${fmt(row.surgical.writtenTokens)} tokens across ` +
          `${row.surgical.sectionsChanged} section(s), reported ` +
          `${fmt(row.surgical.reportedTokens)}  ${(row.surgical.elapsedMs / 1000).toFixed(1)}s  ` +
          `${row.surgical.changesInScope} in scope, ${row.surgical.changesOutOfScope} out`
      );
    } catch (error) {
      row.surgicalError = describe(error);
      console.log(`  surgical             FAILED: ${row.surgicalError}`);
    }

    if (!skipWhole) {
      try {
        const t0 = Date.now();
        const whole = await measureWholeDocument({
          document,
          instruction: INSTRUCTION,
          timeoutMs: JOB_TIMEOUT_MS,
          onProgress: (progress, status) =>
            process.stdout.write(`\r  whole-document  ${status} ${progress}%   `)
        });
        process.stdout.write("\r");

        row.wholeDocument = {
          reportedTokens: whole.reportedTokens,
          writtenTokens: whole.work.output.tokens,
          sectionsChanged: whole.work.sectionsChanged,
          elapsedMs: Date.now() - t0,
          jobId: whole.jobId
        };

        console.log(
          `  whole-document   wrote ${fmt(row.wholeDocument.writtenTokens)} tokens across ` +
            `${row.wholeDocument.sectionsChanged} section(s), reported ` +
            `${fmt(row.wholeDocument.reportedTokens)}  ` +
            `${(row.wholeDocument.elapsedMs / 1000).toFixed(1)}s`
        );
      } catch (error) {
        row.wholeDocumentError = describe(error);
        console.log(`  whole-document       FAILED: ${row.wholeDocumentError}`);
      }
    }

    if (row.surgical !== null && row.wholeDocument !== null) {
      const written = row.wholeDocument.writtenTokens - row.surgical.writtenTokens;

      console.log(
        `  savings          ${fmt(written)} fewer tokens written ` +
          `(${((written / Math.max(1, row.wholeDocument.writtenTokens)) * 100).toFixed(2)}%)`
      );
    }

    console.log("");
    rows.set(pages, row);
    write(
      config.modelTier,
      [...rows.values()].sort((a, b) => a.pages - b.pages)
    );
  }

  const after = await whoami();
  console.log(`Written to ${path.relative(process.cwd(), RESULTS_PATH)}`);
  console.log(
    `SuperDocs operations used: ${quota?.used ?? "?"} before, ${after.quota?.used ?? "?"} after`
  );
}

function write(modelTier: string, rows: BenchmarkRow[]): void {
  const file: BenchmarkFile = {
    generatedAt: stamp(),
    modelTier,
    wordsPerPage: 500,
    instruction: INSTRUCTION,
    rows
  };

  mkdirSync(path.dirname(RESULTS_PATH), { recursive: true });
  writeFileSync(RESULTS_PATH, `${JSON.stringify(file, null, 2)}\n`);
  writeFileSync(path.join(path.dirname(RESULTS_PATH), "RESULTS.md"), renderReport(file));
}

await main();
