import { describe, expect, it } from "vitest";
import { runStaticReview } from "../src/review/runner.js";
import type { ChangedFile } from "../src/review/scanner.js";

describe("static review runner", () => {
  it("returns docs, findings, and a measurable summary", () => {
    const files: ChangedFile[] = [
      {
        path: "README.md",
        status: "modified",
        headContent: "# Title\n\n### Bad\n\nRelease date: TBD"
      },
      {
        path: "src/app.ts",
        status: "modified",
        headContent: "export {};"
      }
    ];

    const result = runStaticReview(files);

    expect(result.summary).toEqual({
      filesScanned: 2,
      docsReviewed: 1,
      findingsGenerated: 2,
      findingsPosted: 2,
      findingsSuppressed: 0
    });
    expect(result.postedFindings.map((finding) => finding.severity)).toEqual([
      "blocker",
      "warning"
    ]);
  });
});

