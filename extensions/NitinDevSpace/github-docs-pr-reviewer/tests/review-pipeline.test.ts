import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { createFakeRepository } from "../src/demo/fake-repository.js";
import { runReviewPipeline } from "../src/pipeline/review-pipeline.js";

async function tempDir() {
  return mkdtemp(path.join(os.tmpdir(), "review-pipeline-"));
}

describe("review pipeline", () => {
  it("posts a review and a preview for a documentation pull request", async () => {
    const { state, client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "abc123",
      files: { "docs/guide.md": "# Guide\n\nUtilize the API.\n" }
    });

    const result = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "abc123"
      },
      artifactsDir: await tempDir()
    });

    expect(result.status).toBe("completed");
    expect(result.review?.summary.docsReviewed).toBe(1);
    expect(result.preview?.mode).toBe("local-html");
    expect(state.reviews).toHaveLength(1);
    expect(state.comments).toHaveLength(1);
    expect(result.stages.map((stage) => stage.stage)).toEqual([
      "fetched_doc_files",
      "ran_static_checks",
      "generated_preview",
      "posted_review",
      "completed"
    ]);
  });

  it("does not post a review when no documentation files changed", async () => {
    const { state, client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "abc123",
      files: { "src/index.ts": "export {};\n" }
    });

    const result = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "abc123"
      },
      artifactsDir: await tempDir()
    });

    expect(result.status).toBe("no-docs-changed");
    expect(state.reviews).toHaveLength(0);
    expect(state.comments).toHaveLength(0);
    expect(result.stages.some((stage) => stage.stage === "ran_static_checks")).toBe(
      true
    );
  });

  it("still posts the review when preview generation fails", async () => {
    const { state, client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "abc123",
      files: { "docs/guide.md": "# Guide\n\nUtilize the API.\n" }
    });

    const result = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "abc123"
      },
      artifactsDir: path.join(os.tmpdir(), "does-not-exist", "readonly"),
      superdocs: {
        async exportDocument() {
          throw new Error("SuperDocs is unreachable");
        }
      }
    });

    expect(result.status).toBe("completed");
    expect(result.preview).toBeUndefined();
    expect(state.reviews).toHaveLength(1);
    expect(
      result.stages.find((stage) => stage.stage === "generated_preview")?.status
    ).toBe("failed");
  });

  it("reports a failed GitHub write instead of claiming the review was posted", async () => {
    const { client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "abc123",
      files: { "docs/guide.md": "# Guide\n\nUtilize the API.\n" }
    });

    client.createPullRequestReview = async () => {
      throw new Error("403 Forbidden");
    };

    const result = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "abc123"
      },
      artifactsDir: await tempDir()
    });

    expect(result.status).toBe("failed");
    expect(result.detail).toContain("403 Forbidden");
    expect(result.published).toBeUndefined();
  });
});
