import { describe, expect, it } from "vitest";
import type { Proposal } from "./domain";
import { renderReviewedExports } from "./export-renderer";

const proposals: Proposal[] = [
  {
    id: "approved-id",
    section: "Analysis",
    before: "",
    after: "<h2>Approved Analysis</h2><p>Approved analysis content.</p>",
    decision: "APPROVED",
    reviewerNote: "Keep",
  },
  {
    id: "rejected-id",
    section: "Analysis",
    before: "",
    after: "<h2>Rejected Analysis</h2><p>Rejected analysis content.</p>",
    decision: "REJECTED",
    reviewerNote: "Remove",
  },
  {
    id: "approved-heading-only",
    section: "Analysis",
    before: "",
    after: "<h2>Analysis</h2>",
    decision: "APPROVED",
    reviewerNote: "Would be orphaned",
  },
];

describe("reviewed HTML renderer", () => {
  const rendered = renderReviewedExports({
    draftHtml:
      "<h1>Memo</h1><h2>Analysis</h2><p>Original approved analysis.</p><h2>Conclusion</h2><p>Conclusion.</p><h2>Confidence level</h2><p>Moderate</p>",
    proposals,
    authorities: [{ title: "Rule", citation: "Code 1" }],
    rows: [{ amount: "1200000.00", source_row_id: "CALC-001" }],
    rejectedAuthorityTitle: "Fabricated authority",
  });

  it("retains approved headings/content and removes rejected blocks", () => {
    expect(rendered.reviewedBase).toContain("Approved Analysis");
    expect(rendered.reviewedBase).toContain("Approved analysis content.");
    expect(rendered.reviewedBase).not.toContain("Rejected Analysis");
    expect(rendered.reviewedBase).not.toContain("Rejected analysis content.");
  });

  it("does not leave an orphan or empty heading", () => {
    expect(rendered.reviewedBase).not.toMatch(
      /<h[1-6][^>]*>[^<]*<\/h[1-6]>\s*<h[1-6]/i,
    );
    expect(rendered.reviewedBase).not.toContain(
      "<h2>Analysis</h2><h2>Conclusion</h2>",
    );
  });

  it("keeps client output free of internal warnings", () => {
    expect(rendered.client).not.toContain("Unsupported-authority warnings");
    expect(rendered.client).not.toContain("Reviewer decision log");
  });

  it("keeps file-ready audit sections", () => {
    expect(rendered.file).toContain("Authorities table");
    expect(rendered.file).toContain("Numeric traceability register");
    expect(rendered.file).toContain("Unsupported-authority warnings");
    expect(rendered.file).toContain("Reviewer decision log");
  });

  it("derives client and file outputs from the same reviewed state", () => {
    expect(rendered.client).toBe(rendered.reviewedBase);
    expect(rendered.file.startsWith(rendered.reviewedBase)).toBe(true);
  });
});
