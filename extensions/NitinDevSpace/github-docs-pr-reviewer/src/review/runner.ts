import { rankFindings } from "./ranker.js";
import { reviewDocumentWithStaticRules } from "./rules.js";
import {
  filterReviewableDocs,
  type ChangedFile,
  type ReviewableDoc
} from "./scanner.js";
import type { Finding } from "./findings.js";

export type StaticReviewResult = {
  docs: ReviewableDoc[];
  findings: Finding[];
  postedFindings: Finding[];
  suppressedFindings: Finding[];
  summary: {
    filesScanned: number;
    docsReviewed: number;
    findingsGenerated: number;
    findingsPosted: number;
    findingsSuppressed: number;
  };
};

export function runStaticReview(files: ChangedFile[]): StaticReviewResult {
  const docs = filterReviewableDocs(files);
  const findings = docs.flatMap((doc) => reviewDocumentWithStaticRules(doc));
  const ranked = rankFindings(findings);

  return {
    docs,
    findings,
    postedFindings: ranked.posted,
    suppressedFindings: ranked.suppressed,
    summary: {
      filesScanned: files.length,
      docsReviewed: docs.length,
      findingsGenerated: findings.length,
      findingsPosted: ranked.posted.length,
      findingsSuppressed: ranked.suppressed.length
    }
  };
}

