import { describe, expect, it } from "vitest";
import type { Chapter, DoNotTranslateRule, Finding } from "../types.js";
import { buildQaReport, renderQaReportAsText } from "./chapterReport.js";

function chapter(id: string, title: string): Chapter {
  return { id, index: 1, title, blocks: [] };
}

function rule(canonicalForm: string): DoNotTranslateRule {
  return { id: `rule-${canonicalForm}`, termId: `t-${canonicalForm}`, canonicalForm, policy: "do_not_translate", caseSensitive: true, reason: "", scope: "this_manuscript" };
}

function finding(overrides: Partial<Finding> & Pick<Finding, "chapterId" | "expected" | "ruleStatus">): Finding {
  return {
    id: `f-${Math.random()}`,
    chapterTitle: "x",
    category: "protected_term",
    severity: "high",
    actual: "wrong",
    ruleDescription: "",
    sourceLocation: { chapterId: overrides.chapterId, chapterTitle: "x", blockIndex: 0, evidenceQuote: "" },
    translatedLocation: null,
    recommendedAction: "",
    confidence: "high",
    ...overrides,
  };
}

describe("buildQaReport", () => {
  const chapters = [chapter("ch01", "Chapter One"), chapter("ch02", "Chapter Two"), chapter("ch03", "Chapter Three")];
  const rules = [rule("Aetherfall"), rule("Xylora")];

  it("reports every chapter as PASS when there are no findings", () => {
    const report = buildQaReport(chapters, rules, []);
    expect(report.totalProtectedTerms).toBe(2);
    expect(report.totalPassed).toBe(2);
    expect(report.chapters.every((c) => c.status === "pass")).toBe(true);
  });

  it("marks only the chapters with findings as 'issues', with a correct per-chapter count", () => {
    const findings = [
      finding({ chapterId: "ch02", expected: "Aetherfall", ruleStatus: "confirmed" }),
      finding({ chapterId: "ch02", expected: "Aetherfall", ruleStatus: "confirmed" }),
    ];
    const report = buildQaReport(chapters, rules, findings);
    expect(report.chapters.find((c) => c.chapterId === "ch01")?.status).toBe("pass");
    expect(report.chapters.find((c) => c.chapterId === "ch02")).toMatchObject({ status: "issues", findingCount: 2 });
    expect(report.chapters.find((c) => c.chapterId === "ch03")?.status).toBe("pass");
  });

  it("reduces totalPassed only for CONFIRMED-rule findings, matching the reference example shape (42 terms, 39 passed)", () => {
    const findings = [finding({ chapterId: "ch01", expected: "Aetherfall", ruleStatus: "confirmed" })];
    const report = buildQaReport(chapters, rules, findings);
    expect(report.totalProtectedTerms).toBe(2);
    expect(report.totalPassed).toBe(1); // Aetherfall failed, Xylora still counts as passed
  });

  it("does NOT reduce totalPassed for a finding against a still-suggested (unconfirmed) term", () => {
    const findings = [finding({ chapterId: "ch01", expected: "SomeUnreviewedTerm", ruleStatus: "suggested" })];
    const report = buildQaReport(chapters, rules, findings);
    // The chapter still shows the issue (it's worth surfacing)...
    expect(report.chapters.find((c) => c.chapterId === "ch01")?.status).toBe("issues");
    // ...but the headline "protected terms passed" count only reflects rules that were
    // actually confirmed and actually enforced -- nothing here was ever approved.
    expect(report.totalProtectedTerms).toBe(2);
    expect(report.totalPassed).toBe(2);
    expect(report.totalFindings).toBe(1);
  });
});

describe("renderQaReportAsText", () => {
  it("renders a readable PASS/issues summary per chapter", () => {
    const chapters = [chapter("ch01", "Down the Rabbit-Hole"), chapter("ch02", "The Pool of Tears")];
    const findings = [finding({ chapterId: "ch02", expected: "Aetherfall", ruleStatus: "confirmed" })];
    const text = renderQaReportAsText(buildQaReport(chapters, [rule("Aetherfall")], findings));
    expect(text).toContain("Down the Rabbit-Hole");
    expect(text).toContain("PASS");
    expect(text).toContain("The Pool of Tears");
    expect(text).toContain("1 issue");
  });
});
