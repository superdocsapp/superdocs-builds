import { describe, expect, it } from "vitest";
import { createFinding, type FindingInput } from "../src/review/findings.js";
import { rankFindings } from "../src/review/ranker.js";

function finding(input: Partial<FindingInput> = {}) {
  return createFinding({
    severity: "suggestion",
    category: "style",
    path: "README.md",
    startLine: 1,
    title: "Suggestion",
    explanation: "Improve wording.",
    confidence: "medium",
    source: "rule",
    ...input
  });
}

describe("finding ranker", () => {
  it("orders blockers before warnings and suggestions", () => {
    const ranked = rankFindings([
      finding({ severity: "suggestion", title: "Suggestion", startLine: 3 }),
      finding({ severity: "blocker", title: "Blocker", startLine: 2 }),
      finding({ severity: "warning", title: "Warning", startLine: 1 })
    ]);

    expect(ranked.posted.map((item) => item.title)).toEqual([
      "Blocker",
      "Warning",
      "Suggestion"
    ]);
  });

  it("caps posted findings and suppresses the rest", () => {
    const ranked = rankFindings(
      [
        finding({ startLine: 1, title: "One" }),
        finding({ startLine: 2, title: "Two" }),
        finding({ startLine: 3, title: "Three" })
      ],
      { maxPosted: 2 }
    );

    expect(ranked.posted).toHaveLength(2);
    expect(ranked.suppressed).toHaveLength(1);
  });
});

