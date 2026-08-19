import { describe, expect, it } from "vitest";
import { summarise, renderReport, type EvalRun } from "@/evals/score";

/**
 * The eval reports a number that goes in a write-up, so the arithmetic behind
 * it is tested. A scoring bug that inflates the headline is the exact failure
 * mode an honest measurement is supposed to prevent.
 */

function run(overrides: Partial<EvalRun> = {}): EvalRun {
  return {
    caseId: "c1",
    declaredBand: "reluctant",
    inferredBand: "reluctant",
    lexiconFindings: 0,
    arm: "baseline",
    letterChars: 800,
    ms: 4000,
    ...overrides,
  };
}

describe("summarise", () => {
  it("reports a perfect run as 100% with zero drift", () => {
    const summary = summarise([run(), run({ caseId: "c2", declaredBand: "solid", inferredBand: "solid" })], "baseline");
    expect(summary.exactMatchRate).toBe(1);
    expect(summary.meanDrift).toBe(0);
    expect(summary.inflationRate).toBe(0);
  });

  it("reports inflation as POSITIVE drift", () => {
    const summary = summarise([run({ declaredBand: "reluctant", inferredBand: "strong" })], "baseline");
    expect(summary.meanDrift).toBe(3);
    expect(summary.inflationRate).toBe(1);
    expect(summary.severeInflationCount).toBe(1);
  });

  it("reports under-claiming as NEGATIVE drift and not as inflation", () => {
    const summary = summarise([run({ declaredBand: "strong", inferredBand: "mixed" })], "baseline");
    expect(summary.meanDrift).toBe(-2);
    expect(summary.inflationRate).toBe(0);
    expect(summary.severeInflationCount).toBe(0);
  });

  it("does not let opposite drifts cancel into a false clean bill of health", () => {
    const summary = summarise(
      [
        run({ declaredBand: "reluctant", inferredBand: "solid" }),
        run({ caseId: "c2", declaredBand: "strong", inferredBand: "mixed" }),
      ],
      "baseline",
    );
    expect(summary.meanDrift).toBe(0);
    // The mean is zero but nothing matched. Exact match rate is what stops
    // this reading as a perfect system.
    expect(summary.exactMatchRate).toBe(0);
    expect(summary.driftStdDev).toBeGreaterThan(0);
  });

  it("excludes errored runs from scoring but still counts them", () => {
    const summary = summarise(
      [run(), run({ caseId: "c2", inferredBand: null, error: "job failed" })],
      "baseline",
    );
    expect(summary.n).toBe(2);
    expect(summary.scored).toBe(1);
    expect(summary.errors).toBe(1);
    expect(summary.exactMatchRate).toBe(1);
  });

  it("keeps the arms separate", () => {
    const runs = [
      run({ arm: "baseline", declaredBand: "reluctant", inferredBand: "strong" }),
      run({ arm: "audited", declaredBand: "reluctant", inferredBand: "reluctant" }),
    ];
    expect(summarise(runs, "baseline").meanDrift).toBe(3);
    expect(summarise(runs, "audited").meanDrift).toBe(0);
  });

  it("reports standard deviation, not just the mean", () => {
    const summary = summarise(
      [
        run({ declaredBand: "solid", inferredBand: "solid" }),
        run({ caseId: "c2", declaredBand: "solid", inferredBand: "strong" }),
        run({ caseId: "c3", declaredBand: "mixed", inferredBand: "solid" }),
      ],
      "baseline",
    );
    expect(summary.driftStdDev).toBeGreaterThan(0);
  });

  it("returns 0 std dev for a single sample rather than NaN", () => {
    expect(summarise([run()], "baseline").driftStdDev).toBe(0);
  });

  it("handles an empty set without dividing by zero", () => {
    const summary = summarise([], "baseline");
    expect(summary.exactMatchRate).toBe(0);
    expect(summary.meanDrift).toBe(0);
    expect(Number.isNaN(summary.driftStdDev)).toBe(false);
  });

  it("reports the tail, not only the average", () => {
    const summary = summarise(
      [
        run({ declaredBand: "solid", inferredBand: "solid" }),
        run({ caseId: "c2", declaredBand: "solid", inferredBand: "solid" }),
        run({ caseId: "c3", declaredBand: "reluctant", inferredBand: "strong" }),
      ],
      "baseline",
    );
    expect(summary.meanDrift).toBe(1);
    expect(summary.worstDrift).toBe(3);
    expect(summary.severeInflationCount).toBe(1);
  });

  it("breaks results down per declared band", () => {
    const summary = summarise(
      [
        run({ declaredBand: "reluctant", inferredBand: "solid" }),
        run({ caseId: "c2", declaredBand: "strong", inferredBand: "strong" }),
      ],
      "baseline",
    );
    const reluctant = summary.perBand.find((b) => b.band === "reluctant");
    expect(reluctant?.inflatedCount).toBe(1);
    expect(summary.perBand.find((b) => b.band === "strong")?.exact).toBe(1);
  });

  it("computes p95 latency, not only p50", () => {
    // Nearest-rank p95 of 20 samples is the 19th, so a SINGLE outlier at the
    // 20th is correctly excluded. That is the definition working, not a bug.
    // Two slow runs put an elevated value at rank 19, which is what a real
    // tail looks like and what p95 is supposed to surface.
    const runs = Array.from({ length: 20 }, (_, i) =>
      run({ caseId: `c${i}`, ms: i >= 18 ? 60_000 : 3000 }),
    );
    const summary = summarise(runs, "baseline");
    expect(summary.p50Ms).toBe(3000);
    expect(summary.p95Ms).toBe(60_000);
  });

  it("does not let a single outlier move p95 at n=20", () => {
    const runs = Array.from({ length: 20 }, (_, i) => run({ caseId: `c${i}`, ms: i === 19 ? 60_000 : 3000 }));
    expect(summarise(runs, "baseline").p95Ms).toBe(3000);
  });
});

describe("renderReport", () => {
  const runs = [
    run({ arm: "baseline", declaredBand: "reluctant", inferredBand: "solid" }),
    run({ arm: "audited", caseId: "c1", declaredBand: "reluctant", inferredBand: "reluctant" }),
  ];

  it("states the method before the result", () => {
    const md = renderReport({
      runs,
      startedAt: "2026-01-01T00:00:00Z",
      model: "m",
      verifierModel: "v",
      operationsSpent: 2,
      notes: [],
    });
    expect(md.indexOf("## Method")).toBeLessThan(md.indexOf("| Exact band match"));
  });

  it("always admits limits", () => {
    const md = renderReport({
      runs,
      startedAt: "t",
      model: "m",
      verifierModel: "v",
      operationsSpent: 2,
      notes: [],
    });
    expect(md).toMatch(/## Limits of this measurement/);
    expect(md).toMatch(/sample is small by design/);
  });

  it("refuses to claim significance from a small ablation", () => {
    const md = renderReport({
      runs,
      startedAt: "t",
      model: "m",
      verifierModel: "v",
      operationsSpent: 2,
      notes: [],
    });
    expect(md).toMatch(/directional evidence, not a\s*significance claim/);
  });

  it("carries run notes such as a stopping-rule abort into the report", () => {
    const md = renderReport({
      runs,
      startedAt: "t",
      model: "m",
      verifierModel: "v",
      operationsSpent: 2,
      notes: ["Stopped at the 20-operation ceiling with 4 letters unrun."],
    });
    expect(md).toMatch(/20-operation ceiling/);
  });
});
