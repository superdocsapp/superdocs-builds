import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { docsToHtml } from "../src/preview/markdown-html.js";
import { generatePreview } from "../src/preview/generator.js";
import type { ReviewableDoc } from "../src/review/scanner.js";
import type { PullRequestTarget } from "../src/github/review-format.js";

const docs: ReviewableDoc[] = [{
  path: "docs/guide.md",
  status: "modified",
  language: "markdown",
  headContent: "# Guide\n\nUse **SuperDocs**.\n\n```ts\nconst ready = true;\n```"
}];

const target: PullRequestTarget = {
  owner: "acme",
  repo: "docs",
  pullNumber: 12,
  headSha: "abcdef1234567890"
};

describe("preview generation", () => {
  it("renders documentation into a styled HTML document", () => {
    const html = docsToHtml(docs, "Guide preview");

    expect(html).toContain("<title>Guide preview</title>");
    expect(html).toContain("<h1>Guide</h1>");
    expect(html).toContain("<strong>SuperDocs</strong>");
    expect(html).toContain("const ready = true;");
  });

  it("treats embedded HTML in a document as text, not as markup", () => {
    const html = docsToHtml(
      [
        {
          path: "docs/notice.md",
          status: "modified",
          language: "markdown",
          headContent: "<script>alert(1)</script>\n\n**Stay**"
        }
      ],
      "Notice"
    );

    expect(html).not.toContain("<script>alert");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("<strong>Stay</strong>");
  });

  it("stores a deterministic local fallback when SuperDocs is unavailable", async () => {
    const artifactsDir = await mkdtemp(path.join(os.tmpdir(), "docs-preview-"));
    const result = await generatePreview({ artifactsDir, target, docs });
    const stored = await readFile(result.artifact.filePath, "utf8");

    expect(result.mode).toBe("local-html");
    expect(result.artifact.filePath).toContain("previews/acme/docs/pr-12/abcdef123456");
    expect(stored).toContain("Guide");
  });

  it("stores the exported SuperDocs document", async () => {
    const artifactsDir = await mkdtemp(path.join(os.tmpdir(), "docs-preview-"));
    let receivedHtml = "";
    const result = await generatePreview({
      artifactsDir,
      target,
      docs,
      format: "pdf",
      client: {
        async exportDocument(input) {
          receivedHtml = input.html;
          expect(input.idempotencyKey).toContain(target.headSha);
          return {
            data: new Uint8Array([37, 80, 68, 70]),
            contentType: "application/pdf",
            filename: "preview.pdf"
          };
        }
      }
    });

    expect(result.mode).toBe("superdocs");
    expect(result.artifact.filePath.endsWith("preview.pdf")).toBe(true);
    expect([...await readFile(result.artifact.filePath)]).toEqual([37, 80, 68, 70]);
    expect(receivedHtml).toContain("Guide");
  });
});
