import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runApplyCommand } from "../src/commands/apply-runner.js";
import { createFakeRepository } from "../src/demo/fake-repository.js";
import { promptInjectionFixture } from "../src/demo/fixtures.js";
import { runDemo } from "../src/demo/run-demo.js";
import { runReviewPipeline } from "../src/pipeline/review-pipeline.js";

async function tempDir() {
  return mkdtemp(path.join(os.tmpdir(), "docs-demo-"));
}

describe("demo run", () => {
  it("walks the whole flow and reports each step", async () => {
    const lines: string[] = [];
    await runDemo({
      artifactsDir: await tempDir(),
      log: (line) => lines.push(line)
    });

    const output = lines.join("\n");

    expect(output).toContain("A docs pull request arrives");
    expect(output).toContain("Documentation files reviewed: 2");
    expect(output).toContain("Committed demo0000001");
    expect(output).toContain("never commits twice");
    expect(output).toContain("Commits made in total: 1");
    expect(output).toContain("Where the time went");
    expect(output).toContain("completed: ok");
  });

  it("shows the app refusing an advisory fix and an unauthorized user", async () => {
    const lines: string[] = [];
    await runDemo({
      artifactsDir: await tempDir(),
      log: (line) => lines.push(line)
    });

    const output = lines.join("\n");

    expect(output).toContain("will not guess one");
    expect(output).toContain("does not have write access");
  });
});

describe("documents that try to give orders", () => {
  it("reviews an instruction-carrying document as content, and applies nothing on its own", async () => {
    const { state, client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "demo0000000",
      files: promptInjectionFixture
    });

    const result = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "demo0000000"
      },
      artifactsDir: await tempDir()
    });

    expect(result.status).toBe("completed");

    // The document asked for an approving review and for every fix to be applied.
    // Neither happened: the review is a comment, and no commit was made.
    expect(result.published?.event).toBe("COMMENT");
    expect(state.commits).toHaveLength(0);

    // The instruction text is reported as a finding location, not obeyed.
    const findings = result.review?.findings ?? [];
    expect(findings.some((finding) => finding.path === "docs/notice.md")).toBe(true);
  });

  it("only acts when a human comments the command", async () => {
    const { state, client } = createFakeRepository({
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      headSha: "demo0000000",
      files: promptInjectionFixture
    });

    const review = await runReviewPipeline({
      client,
      target: {
        owner: "acme",
        repo: "handbook",
        pullNumber: 1,
        headSha: "demo0000000"
      },
      artifactsDir: await tempDir()
    });

    const fixable = (review.review?.findings ?? []).find(
      (finding) => finding.autofix
    );
    expect(fixable).toBeDefined();
    expect(state.commits).toHaveLength(0);

    const applied = await runApplyCommand({
      client,
      owner: "acme",
      repo: "handbook",
      pullNumber: 1,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId: fixable!.id }
    });

    expect(applied.status).toBe("applied");
    expect(state.commits).toHaveLength(1);
  });
});
