import { describe, expect, it } from "vitest";
import {
  filterReviewableDocs,
  isDocumentationPath,
  type ChangedFile
} from "../src/review/scanner.js";

describe("documentation scanner", () => {
  it("detects documentation paths", () => {
    expect(isDocumentationPath("README.md")).toBe(true);
    expect(isDocumentationPath("docs/getting-started.md")).toBe(true);
    expect(isDocumentationPath("guides/setup.mdx")).toBe(true);
    expect(isDocumentationPath("src/app.ts")).toBe(false);
    expect(isDocumentationPath("docs/image.png")).toBe(false);
  });

  it("filters removed and non-doc files", () => {
    const files: ChangedFile[] = [
      { path: "README.md", status: "modified", headContent: "# Hello" },
      { path: "src/app.ts", status: "modified", headContent: "console.log()" },
      { path: "docs/old.md", status: "removed" },
      { path: "docs/guide.mdx", status: "added", headContent: "# Guide" }
    ];

    const docs = filterReviewableDocs(files);

    expect(docs.map((doc) => doc.path)).toEqual(["README.md", "docs/guide.mdx"]);
    expect(docs.map((doc) => doc.language)).toEqual(["markdown", "mdx"]);
  });
});

