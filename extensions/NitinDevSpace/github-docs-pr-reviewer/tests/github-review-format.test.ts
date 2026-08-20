import { describe, expect, it } from "vitest";
import {
  formatInlineFindingBody,
  formatSummaryComment,
  reviewEventFor,
  summaryMarker
} from "../src/github/review-format.js";
import { createFinding } from "../src/review/findings.js";
import type { StaticReviewResult } from "../src/review/runner.js";

function reviewResult(): StaticReviewResult {
  const finding = createFinding({
    severity: "warning",
    category: "structure",
    path: "README.md",
    startLine: 4,
    title: "Heading level skips",
    explanation: "Keep heading levels sequential.",
    confidence: "high",
    source: "rule"
  });

  return {
    docs: [],
    findings: [finding],
    postedFindings: [finding],
    suppressedFindings: [],
    summary: {
      filesScanned: 2,
      docsReviewed: 1,
      findingsGenerated: 1,
      findingsPosted: 1,
      findingsSuppressed: 0
    }
  };
}

describe("GitHub review formatting", () => {
  it("builds a summary comment with marker, counts, commands, and preview link", () => {
    const body = formatSummaryComment({
      target: {
        owner: "octo",
        repo: "demo",
        pullNumber: 4,
        headSha: "abc123"
      },
      review: reviewResult(),
      preview: {
        label: "DOCX preview",
        url: "https://example.com/preview.docx"
      }
    });

    expect(body).toContain(summaryMarker("abc123"));
    expect(body).toContain("Docs reviewed: 1");
    expect(body).toContain("Preview: [DOCX preview](https://example.com/preview.docx)");
    expect(body).toContain("/superdocs apply <finding-id>");
  });

  it("formats inline finding comments with finding metadata", () => {
    const finding = reviewResult().postedFindings[0];
    const body = formatInlineFindingBody(finding);

    expect(body).toContain("**Heading level skips**");
    expect(body).toContain(`Finding ID: \`${finding.id}\``);
    expect(body).toContain("Severity: `warning`");
  });

  it("requests changes only when blocker findings exist", () => {
    expect(reviewEventFor(reviewResult().postedFindings)).toBe("COMMENT");
    expect(
      reviewEventFor([
        createFinding({
          severity: "blocker",
          category: "style",
          path: "README.md",
          startLine: 1,
          title: "Unresolved placeholder",
          explanation: "Replace TBD.",
          confidence: "high",
          source: "rule"
        })
      ])
    ).toBe("REQUEST_CHANGES");
  });
});

