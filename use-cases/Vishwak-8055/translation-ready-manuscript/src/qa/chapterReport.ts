import type { Chapter, ChapterQaSummary, DoNotTranslateRule, Finding, TranslationQaReport } from "../types.js";

/**
 * Assembles the chapter-by-chapter mismatch report from a flat Finding list.
 *
 * The headline "N protected terms, M passed" count is scoped to CONFIRMED
 * rules only -- that's the number the task document's own example reports
 * ("42 protected terms, 39 passed, 3 issues"), and it's the number with
 * real authority behind it. Findings against still-suggested candidates
 * still appear in the per-chapter breakdown (missing an unreviewed
 * candidate's change is its own failure worth surfacing) but don't move
 * the headline pass count, since no rule was actually broken -- nothing
 * was ever approved to enforce.
 */
export function buildQaReport(sourceChapters: Chapter[], confirmedRules: DoNotTranslateRule[], findings: Finding[]): TranslationQaReport {
  const confirmedFindingTermIds = new Set(
    findings.filter((f) => f.ruleStatus === "confirmed" && f.category === "protected_term").map((f) => f.expected),
  );
  const rulesWithFindings = confirmedRules.filter((r) => confirmedFindingTermIds.has(r.canonicalForm)).length;

  const chapters: ChapterQaSummary[] = sourceChapters.map((chapter) => {
    const chapterFindings = findings.filter((f) => f.chapterId === chapter.id);
    return {
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      status: chapterFindings.length > 0 ? "issues" : "pass",
      findingCount: chapterFindings.length,
    };
  });

  return {
    generatedAt: new Date().toISOString(),
    totalProtectedTerms: confirmedRules.length,
    totalPassed: confirmedRules.length - rulesWithFindings,
    totalFindings: findings.length,
    chapters,
    findings,
  };
}

/** Renders the report as the plain-text chapter list shown throughout the design docs -- "Chapter 1  PASS", "Chapter 3  1 issue". Useful for the demo script and for quick human review outside the packet UI. */
export function renderQaReportAsText(report: TranslationQaReport): string {
  const lines: string[] = [];
  lines.push("TRANSLATION QA");
  lines.push("");
  lines.push(`${report.totalProtectedTerms} protected terms`);
  lines.push(`${report.totalPassed} passed`);
  lines.push(`${report.totalFindings} finding(s)`);
  lines.push("");
  for (const ch of report.chapters) {
    const label = ch.status === "pass" ? "PASS" : `${ch.findingCount} issue${ch.findingCount === 1 ? "" : "s"}`;
    lines.push(`${ch.chapterTitle.padEnd(40)} ${label}`);
  }
  return lines.join("\n");
}
