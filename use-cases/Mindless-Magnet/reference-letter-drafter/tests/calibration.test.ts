import { describe, expect, it } from "vitest";
import { runDeterministicAudit } from "@/lib/calibration/deterministicAudit";
import { runAudit } from "@/lib/calibration";
import { extractJsonObject, runVerifier } from "@/lib/calibration/verifier";
import type { Intake, StrengthBand } from "@/lib/types";

/**
 * The product claim is one sentence: a lukewarm reference reads as lukewarm
 * rather than being inflated. These tests are that claim, written down.
 *
 * They also cover the thing that makes a checker useless in practice, which is
 * false positives. A tool that flags every letter is a tool people click past.
 */

function intake(overrides: Partial<Intake> = {}): Intake {
  return {
    writerName: "Dr Farah Nasser",
    writerEmail: "f.nasser@example.edu",
    writerRole: "Associate Professor of Materials Science",
    subjectName: "Tomas Rivera",
    subjectRole: "MSc student",
    relationship: "I supervised his master's thesis.",
    relationshipDurationMonths: 14,
    purpose: "graduate_school",
    strengthBand: "solid",
    evidence: [{ claim: "Completed his thesis on schedule", evidence: "Submitted in month 12 of a 12-month programme" }],
    reservations: "",
    lengthPreference: "standard",
    ...overrides,
  };
}

const LUKEWARM_BUT_INFLATED = `
Dear Committee,

It is a pleasure to recommend Tomas Rivera. He was an outstanding member of my
group and I recommend him without reservation. He completed his thesis on
schedule and was a tremendous asset to the laboratory.

Sincerely,
Dr Farah Nasser
`;

const HONESTLY_LUKEWARM = `
Dear Committee,

I supervised Tomas Rivera's master's thesis and can confirm he completed it on
schedule. He met the requirements of the programme.

He worked independently on routine tasks, though he did struggle when the
direction of the project changed, and he needed more supervision at those points
than I would expect at this level. I cannot speak to his performance in a team
setting, as his project was individual.

Sincerely,
Dr Farah Nasser
`;

describe("deterministic band audit", () => {
  it("flags an inflated letter that was declared reluctant", () => {
    const findings = runDeterministicAudit({
      text: LUKEWARM_BUT_INFLATED,
      band: "reluctant",
      reservations: "",
    });

    const titles = findings.map((f) => f.title).join(" | ");
    expect(findings.length).toBeGreaterThanOrEqual(3);
    expect(titles).toMatch(/outstanding/i);
    expect(titles).toMatch(/without reservation/i);
    expect(findings.every((f) => f.severity === "high")).toBe(true);
  });

  it("passes an honestly lukewarm letter with no findings", () => {
    const findings = runDeterministicAudit({
      text: HONESTLY_LUKEWARM,
      band: "reluctant",
      reservations: "He struggled when the project direction changed and needed more supervision.",
    });
    expect(findings).toEqual([]);
  });

  it("allows superlatives in the strong band", () => {
    const findings = runDeterministicAudit({
      text: LUKEWARM_BUT_INFLATED,
      band: "strong",
      reservations: "",
    });
    expect(findings).toEqual([]);
  });

  it("flags superlatives but not warmth in the solid band", () => {
    const findings = runDeterministicAudit({
      text: "He was an exceptional analyst and it is a pleasure to recommend him.",
      band: "solid",
      reservations: "",
    });
    const titles = findings.map((f) => f.title).join(" | ");
    expect(titles).toMatch(/exceptional/i);
    // "it is a pleasure" is honest at solid; only mixed and reluctant ban it.
    expect(titles).not.toMatch(/pleasure/i);
  });

  it("catches the silent inflation: a mixed letter with no qualifier anywhere", () => {
    const findings = runDeterministicAudit({
      text: "Tomas met the requirements of the programme and submitted his thesis on time. He is a capable student.",
      band: "mixed",
      reservations: "",
    });
    expect(findings.map((f) => f.id)).toContain("band-no-qualifier");
  });

  it("does not fire the no-qualifier check on the strong band", () => {
    const findings = runDeterministicAudit({
      text: "Tomas is a capable student who submitted on time.",
      band: "strong",
      reservations: "",
    });
    expect(findings).toEqual([]);
  });

  it("flags a reservation that never made it into the letter", () => {
    const findings = runDeterministicAudit({
      text: HONESTLY_LUKEWARM,
      band: "reluctant",
      reservations: "He was frequently late to laboratory meetings.",
    });
    const dropped = findings.filter((f) => f.kind === "dropped_reservation");
    expect(dropped).toHaveLength(1);
    expect(dropped[0].excerpt).toMatch(/late to laboratory meetings/);
  });

  it("accepts a reservation that was rephrased rather than copied", () => {
    const findings = runDeterministicAudit({
      text: "He did struggle when the direction of the project changed and needed supervision at those points.",
      band: "reluctant",
      reservations: "Struggled when the project direction changed; needed supervision.",
    });
    expect(findings.filter((f) => f.kind === "dropped_reservation")).toHaveLength(0);
  });

  it("does not flag 'outstanding' used in a financial sense", () => {
    const findings = runDeterministicAudit({
      text: "He reconciled the outstanding balance on the grant account each month. He did struggle with deadlines.",
      band: "reluctant",
      reservations: "",
    });
    expect(findings.map((f) => f.title).join(" ")).not.toMatch(/outstanding/i);
  });

  it("does not flag substrings inside longer words", () => {
    const findings = runDeterministicAudit({
      text: "The team used a preexceptionalised process. However, results were limited.",
      band: "reluctant",
      reservations: "",
    });
    expect(findings.map((f) => f.title).join(" ")).not.toMatch(/exceptional/i);
  });

  it("reports one finding per phrase, not one per occurrence", () => {
    const findings = runDeterministicAudit({
      text: "Exceptional. Truly exceptional. An exceptional candidate. However, limited experience.",
      band: "solid",
      reservations: "",
    });
    expect(findings.filter((f) => f.title.toLowerCase().includes("exceptional"))).toHaveLength(1);
  });

  it("returns nothing for an empty letter rather than a pile of false findings", () => {
    expect(runDeterministicAudit({ text: "", band: "reluctant", reservations: "x" })).toEqual([]);
  });
});

describe("verifier", () => {
  it("reports itself unavailable when no model is configured, and does not throw", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "reluctant",
      config: null,
    });
    expect(result.status).toBe("unavailable");
    expect(result.findings).toEqual([]);
    expect(result.reason).toMatch(/SUPERDOCS_API_KEY is not set/i);
  });

  it("degrades to 'failed' when the model call throws, keeping the letter", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "reluctant",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => {
        throw new Error("connection reset");
      },
    });
    expect(result.status).toBe("failed");
    expect(result.reason).toMatch(/connection reset/);
  });

  it("discards non-JSON output instead of guessing at it", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "reluctant",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => "I think the letter is quite good actually!",
    });
    expect(result.status).toBe("failed");
    expect(result.findings).toEqual([]);
  });

  it("raises a high-severity finding when inferred band is two steps warmer", async () => {
    const result = await runVerifier({
      letterText: LUKEWARM_BUT_INFLATED,
      evidence: [],
      declaredBand: "reluctant",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () =>
        JSON.stringify({ inferred_band: "strong", band_reasoning: "Unreserved endorsement.", unsupported_claims: [] }),
    });
    expect(result.status).toBe("ok");
    expect(result.inferredBand).toBe("strong");
    const drift = result.findings.find((f) => f.id === "verifier-band-drift");
    expect(drift?.severity).toBe("high");
    expect(drift?.title).toMatch(/warmer than you meant/i);
  });

  it("says 'cooler' rather than 'warmer' when the letter under-claims", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "strong",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => JSON.stringify({ inferred_band: "reluctant", band_reasoning: "Faint praise." }),
    });
    expect(result.findings[0].title).toMatch(/cooler than you meant/i);
  });

  it("produces no drift finding when the bands agree", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "reluctant",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => JSON.stringify({ inferred_band: "reluctant", unsupported_claims: [] }),
    });
    expect(result.findings).toEqual([]);
  });

  it("turns unsupported claims into findings that quote the letter", async () => {
    const result = await runVerifier({
      letterText: LUKEWARM_BUT_INFLATED,
      evidence: [],
      declaredBand: "solid",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () =>
        JSON.stringify({
          inferred_band: "solid",
          unsupported_claims: [{ claim: "a tremendous asset to the laboratory", why: "No supporting fact." }],
        }),
    });
    const unsupported = result.findings.filter((f) => f.kind === "unsupported_claim");
    expect(unsupported).toHaveLength(1);
    expect(unsupported[0].excerpt).toMatch(/tremendous asset/);
  });

  it("ignores an unknown band string rather than trusting it", async () => {
    const result = await runVerifier({
      letterText: HONESTLY_LUKEWARM,
      evidence: [],
      declaredBand: "reluctant",
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => JSON.stringify({ inferred_band: "amazing" }),
    });
    expect(result.inferredBand).toBeUndefined();
  });
});

describe("extractJsonObject", () => {
  it("handles bare JSON, fenced JSON, and JSON with surrounding prose", () => {
    const target = { inferred_band: "solid" };
    expect(extractJsonObject(JSON.stringify(target))).toEqual(target);
    expect(extractJsonObject("```json\n" + JSON.stringify(target) + "\n```")).toEqual(target);
    expect(extractJsonObject("Here you go:\n" + JSON.stringify(target) + "\nHope that helps.")).toEqual(target);
  });

  it("throws rather than returning a partial object", () => {
    expect(() => extractJsonObject("no json here")).toThrow();
  });
});

describe("runAudit end to end, with no network", () => {
  it("reports which checks ran, so a skipped check is never read as a pass", async () => {
    const report = await runAudit({
      letterHtml: `<p>${HONESTLY_LUKEWARM}</p>`,
      intake: intake({ strengthBand: "reluctant", reservations: "He struggled when the direction changed." }),
      config: null,
    });

    expect(report.checks.lexicon).toBe("ran");
    expect(report.checks.verifier).toBe("unavailable");
    expect(report.findings).toEqual([]);
    expect(report.verifierNote).toMatch(/did not run/i);
  });

  it("records per-stage timings so a run can say where the time went", async () => {
    const report = await runAudit({
      letterHtml: "<p>He was outstanding.</p>",
      intake: intake({ strengthBand: "reluctant", reservations: "Some concerns." }),
      config: null,
    });
    expect(Object.keys(report.timings)).toEqual(
      expect.arrayContaining(["extract_text", "lexicon", "injection_scan", "verifier"]),
    );
  });

  it("computes signed drift, positive meaning inflated", async () => {
    const report = await runAudit({
      letterHtml: `<p>${LUKEWARM_BUT_INFLATED}</p>`,
      intake: intake({ strengthBand: "reluctant", reservations: "Concerns about independence." }),
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => JSON.stringify({ inferred_band: "strong" }),
    });
    expect(report.drift).toBe(3);
    expect(report.inferredBand).toBe("strong");
  });

  it("sorts high-severity findings to the top of the review list", async () => {
    const report = await runAudit({
      letterHtml: `<p>${LUKEWARM_BUT_INFLATED}</p>`,
      intake: intake({ strengthBand: "reluctant", reservations: "Concerns." }),
      config: { baseUrl: "http://x", apiKey: "k" },
      caller: async () => JSON.stringify({ inferred_band: "solid" }),
    });
    const severities = report.findings.map((f) => f.severity);
    const firstMedium = severities.indexOf("medium");
    if (firstMedium !== -1) {
      expect(severities.slice(firstMedium).every((s) => s !== "high")).toBe(true);
    }
  });

  it("gives a clean corpus an honest report of no findings", async () => {
    const report = await runAudit({
      letterHtml: `<p>Tomas completed his thesis on schedule, submitting in month 12 of a 12-month programme. He is a capable student.</p>`,
      intake: intake({ strengthBand: "solid" }),
      config: null,
    });
    expect(report.findings).toEqual([]);
  });
});

const ALL_BANDS: StrengthBand[] = ["strong", "solid", "mixed", "reluctant"];

describe("band lexicon coverage", () => {
  it("every band produces a defined audit result", async () => {
    for (const band of ALL_BANDS) {
      const report = await runAudit({
        letterHtml: "<p>A short factual letter. However, limited scope.</p>",
        intake: intake({ strengthBand: band, reservations: band === "strong" ? "" : "Some limits." }),
        config: null,
      });
      expect(report.declaredBand).toBe(band);
    }
  });
});
