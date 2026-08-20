import { describe, expect, it } from "vitest";
import { reviewDocumentWithStaticRules } from "../src/review/rules.js";
import type { ReviewableDoc } from "../src/review/scanner.js";

function doc(headContent: string): ReviewableDoc {
  return {
    path: "docs/getting-started.md",
    status: "modified",
    language: "markdown",
    headContent
  };
}

describe("static review rules", () => {
  it("flags heading level skips", () => {
    const findings = reviewDocumentWithStaticRules(
      doc("# Title\n\n### Skipped heading")
    );

    expect(findings).toMatchObject([
      {
        severity: "warning",
        category: "structure",
        startLine: 3,
        title: "Heading level skips"
      }
    ]);
  });

  it("flags missing image alt text", () => {
    const findings = reviewDocumentWithStaticRules(doc("![](./hero.png)"));

    expect(findings[0]).toMatchObject({
      severity: "warning",
      category: "structure",
      title: "Image is missing alt text"
    });
  });

  it("flags unresolved placeholders as blockers", () => {
    const findings = reviewDocumentWithStaticRules(doc("Release date: TBD"));

    expect(findings[0]).toMatchObject({
      severity: "blocker",
      category: "style",
      title: "Unresolved placeholder"
    });
  });

  it("flags suspicious relative links without claiming full repo proof", () => {
    const findings = reviewDocumentWithStaticRules(
      doc("[Broken](../missing-page.md)")
    );

    expect(findings[0]).toMatchObject({
      severity: "warning",
      category: "broken-link",
      source: "link-checker"
    });
  });

  it("flags style wording suggestions", () => {
    const findings = reviewDocumentWithStaticRules(
      doc("Click here to utilize the API.")
    );

    expect(findings.map((finding) => finding.title)).toEqual([
      "Style guide wording",
      "Style guide wording"
    ]);
  });
});

