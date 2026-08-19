import { BANDS } from "../lib/calibration/lexicon";
import type { StrengthBand } from "../lib/types";

/**
 * Scoring for the calibration eval.
 *
 * The headline number is NOT accuracy. Accuracy hides the thing that matters:
 * this tool exists because reference letters drift WARM, so a 60% accurate
 * system that only ever errs cold is a different product from a 60% accurate
 * system that only ever errs warm. Signed drift separates them, and it is the
 * number to read first.
 *
 * Everything here is pure arithmetic over recorded results, so it is unit
 * tested and runs with no key.
 */

export interface EvalRun {
  caseId: string;
  declaredBand: StrengthBand;
  inferredBand: StrengthBand | null;
  /** Deterministic findings raised on this letter. */
  lexiconFindings: number;
  /** Whether the audit gate was applied before scoring. */
  arm: "baseline" | "audited";
  letterChars: number;
  ms: number;
  error?: string;
}

export interface BandBreakdown {
  band: StrengthBand;
  n: number;
  exact: number;
  meanDrift: number;
  inflatedCount: number;
  deflatedCount: number;
}

export interface ArmSummary {
  arm: "baseline" | "audited";
  n: number;
  scored: number;
  errors: number;
  /** Share of letters whose inferred band equals the declared band. */
  exactMatchRate: number;
  /** Mean signed drift. Positive means the letters read warmer than declared. */
  meanDrift: number;
  /** Sample standard deviation of signed drift. */
  driftStdDev: number;
  /** Share of letters that read warmer than declared, at all. */
  inflationRate: number;
  /** The tail: letters that read two or more bands warmer. */
  severeInflationCount: number;
  worstDrift: number;
  /** Letters where the deterministic layer raised at least one finding. */
  lexiconFlagRate: number;
  p50Ms: number;
  p95Ms: number;
  perBand: BandBreakdown[];
}

function drift(run: EvalRun): number | null {
  if (!run.inferredBand) return null;
  return BANDS[run.inferredBand].rank - BANDS[run.declaredBand].rank;
}

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** Sample standard deviation. Returns 0 for n < 2, where it is undefined. */
function stdDev(values: number[]): number {
  if (values.length < 2) return 0;
  const m = mean(values);
  const variance = values.reduce((acc, v) => acc + (v - m) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance);
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}

export function summarise(runs: EvalRun[], arm: "baseline" | "audited"): ArmSummary {
  const armRuns = runs.filter((r) => r.arm === arm);
  const scored = armRuns.filter((r) => r.inferredBand !== null && !r.error);
  const drifts = scored.map((r) => drift(r)!).filter((d) => d !== null);

  const bands = [...new Set(armRuns.map((r) => r.declaredBand))];
  const perBand: BandBreakdown[] = bands.map((band) => {
    const inBand = scored.filter((r) => r.declaredBand === band);
    const bandDrifts = inBand.map((r) => drift(r)!);
    return {
      band,
      n: inBand.length,
      exact: bandDrifts.filter((d) => d === 0).length,
      meanDrift: Number(mean(bandDrifts).toFixed(3)),
      inflatedCount: bandDrifts.filter((d) => d > 0).length,
      deflatedCount: bandDrifts.filter((d) => d < 0).length,
    };
  });

  return {
    arm,
    n: armRuns.length,
    scored: scored.length,
    errors: armRuns.filter((r) => r.error).length,
    exactMatchRate: scored.length ? Number((drifts.filter((d) => d === 0).length / scored.length).toFixed(3)) : 0,
    meanDrift: Number(mean(drifts).toFixed(3)),
    driftStdDev: Number(stdDev(drifts).toFixed(3)),
    inflationRate: scored.length ? Number((drifts.filter((d) => d > 0).length / scored.length).toFixed(3)) : 0,
    severeInflationCount: drifts.filter((d) => d >= 2).length,
    worstDrift: drifts.length ? Math.max(...drifts) : 0,
    lexiconFlagRate: armRuns.length
      ? Number((armRuns.filter((r) => r.lexiconFindings > 0).length / armRuns.length).toFixed(3))
      : 0,
    p50Ms: Math.round(percentile(armRuns.map((r) => r.ms), 50)),
    p95Ms: Math.round(percentile(armRuns.map((r) => r.ms), 95)),
    perBand,
  };
}

/**
 * Markdown report.
 *
 * Method before result, variance alongside the mean, tail behaviour rather than
 * only an average, and limits admitted at the bottom. Written by the harness so
 * the numbers in the repository can never drift from the numbers that were
 * measured.
 */
export function renderReport(params: {
  runs: EvalRun[];
  startedAt: string;
  model: string;
  verifierModel: string;
  operationsSpent: number;
  notes: string[];
}): string {
  const arms: ("baseline" | "audited")[] = ["baseline", "audited"];
  const present = arms.filter((arm) => params.runs.some((r) => r.arm === arm));
  const summaries = present.map((arm) => summarise(params.runs, arm));

  const lines: string[] = [];

  lines.push("# Calibration eval");
  lines.push("");
  lines.push(`Generated by \`npm run eval\` at ${params.startedAt}. Do not edit by hand.`);
  lines.push("");
  lines.push("## Method, stated before the result");
  lines.push("");
  lines.push(
    "Each synthetic intake in `evals/fixtures/intakes.json` declares a strength band. The drafter " +
      "produces a letter. A **second, isolated SuperDocs chat turn** (fresh session, no cross-session " +
      "memory) then reads the letter alone, with no access to the declared band, the intake, or the " +
      "drafting prompt, and infers what band a reader would take from it. Drift is the inferred rank " +
      "minus the declared rank on a four-point scale (reluctant 1, mixed 2, solid 3, strong 4).",
  );
  lines.push("");
  lines.push(
    "**Positive drift means the letter reads warmer than the writer meant.** That is the failure " +
      "this tool exists to catch, so it is reported signed rather than as an absolute error.",
  );
  lines.push("");
  lines.push(`- Drafting model: \`${params.model}\``);
  lines.push(`- Verifier model: \`${params.verifierModel}\``);
  lines.push(`- SuperDocs operations spent: ${params.operationsSpent}`);
  lines.push(`- Raw per-run data: \`evals/results/runs.jsonl\` (committed)`);
  lines.push("");

  for (const summary of summaries) {
    const label = summary.arm === "baseline" ? "Baseline (band stated in the prompt only)" : "Audited (calibration gate applied)";
    lines.push(`## ${label}`);
    lines.push("");
    lines.push(`n = ${summary.n}, scored = ${summary.scored}, errors = ${summary.errors}`);
    lines.push("");
    lines.push("| Metric | Value |");
    lines.push("| --- | --- |");
    lines.push(`| Exact band match | ${(summary.exactMatchRate * 100).toFixed(1)}% |`);
    lines.push(`| Mean signed drift | ${summary.meanDrift >= 0 ? "+" : ""}${summary.meanDrift} |`);
    lines.push(`| Drift std dev | ${summary.driftStdDev} |`);
    lines.push(`| Inflation rate (drift > 0) | ${(summary.inflationRate * 100).toFixed(1)}% |`);
    lines.push(`| Severe inflation (drift >= 2) | ${summary.severeInflationCount} of ${summary.scored} |`);
    lines.push(`| Worst single drift | ${summary.worstDrift >= 0 ? "+" : ""}${summary.worstDrift} |`);
    lines.push(`| Lexicon flagged something | ${(summary.lexiconFlagRate * 100).toFixed(1)}% |`);
    lines.push(`| Latency p50 / p95 | ${summary.p50Ms}ms / ${summary.p95Ms}ms |`);
    lines.push("");
    lines.push("Per declared band:");
    lines.push("");
    lines.push("| Band | n | Exact | Mean drift | Read warmer | Read cooler |");
    lines.push("| --- | --- | --- | --- | --- | --- |");
    for (const band of summary.perBand) {
      lines.push(
        `| ${band.band} | ${band.n} | ${band.exact}/${band.n} | ${band.meanDrift >= 0 ? "+" : ""}${band.meanDrift} | ${band.inflatedCount} | ${band.deflatedCount} |`,
      );
    }
    lines.push("");
  }

  if (summaries.length === 2) {
    const [baseline, audited] = summaries;
    const delta = Number((audited.meanDrift - baseline.meanDrift).toFixed(3));
    lines.push("## Did the audit gate change anything");
    lines.push("");
    lines.push(
      `Mean signed drift moved from ${baseline.meanDrift >= 0 ? "+" : ""}${baseline.meanDrift} to ` +
        `${audited.meanDrift >= 0 ? "+" : ""}${audited.meanDrift}, a change of ${delta >= 0 ? "+" : ""}${delta}. ` +
        `Severe inflations went from ${baseline.severeInflationCount} to ${audited.severeInflationCount}.`,
    );
    lines.push("");
    lines.push(
      "Read this with the sample size in mind. At this n a difference of one letter moves the mean " +
        "noticeably, and the standard deviations above overlap. This is directional evidence, not a " +
        "significance claim, and it is reported that way deliberately.",
    );
    lines.push("");
  }

  lines.push("## Limits of this measurement");
  lines.push("");
  lines.push(
    "- The sample is small by design. Each letter costs a SuperDocs operation, and the harness has " +
      "a hard `--max-ops` stopping rule so a run cannot quietly drain a free-tier budget.",
  );
  lines.push(
    "- The ground truth is the band a human typed into a fixture, not an expert consensus. A panel " +
      "of real referees would disagree with each other at the boundaries, particularly solid/mixed.",
  );
  lines.push(
    "- The verifier is a language model. It is blind to the declared band, which removes the obvious " +
      "bias, but it is not a neutral instrument and its own tendencies are unmeasured here.",
  );
  lines.push(
    "- Fixtures are synthetic and written by one person, so they share a voice. Real intakes are " +
      "messier, shorter, and more contradictory than these.",
  );
  lines.push(
    "- Latency figures include network time for two separate SuperDocs chat calls (draft, then " +
      "verify) and are not a benchmark of either one alone.",
  );

  if (params.notes.length) {
    lines.push("");
    lines.push("## Run notes");
    lines.push("");
    for (const note of params.notes) lines.push(`- ${note}`);
  }

  lines.push("");
  return lines.join("\n");
}
