import type { GitHubApplyClient } from "../github/apply-client.js";
import { loadPullRequestDocs } from "../github/pr-context.js";
import type { PullRequestTarget } from "../github/review-format.js";
import {
  publishPullRequestReview,
  type GitHubReviewClient,
  type PublishReviewResult
} from "../github/review-publisher.js";
import { generatePreview, previewLink } from "../preview/generator.js";
import type { StaticReviewResult } from "../review/runner.js";
import { runStaticReview } from "../review/runner.js";
import { detectDocLanguage } from "../review/scanner.js";
import type {
  SuperDocsClient,
  SuperDocsExportFormat
} from "../superdocs/client.js";
import { StageRecorder, type Clock, type StageRecord } from "./stages.js";

export type DocsReviewClient = GitHubApplyClient & GitHubReviewClient;

export type ReviewPipelineResult = {
  status: "completed" | "no-docs-changed" | "failed";
  target: PullRequestTarget;
  review?: StaticReviewResult;
  published?: PublishReviewResult;
  preview?: {
    mode: "superdocs" | "local-html";
    url: string;
  };
  skippedFiles: Array<{ path: string; reason: string }>;
  stages: StageRecord[];
  totalMilliseconds: number;
  detail?: string;
};

/**
 * Runs one documentation review for one pull request head commit.
 *
 * The preview is best-effort on purpose: if SuperDocs or the filesystem fails, the
 * run records the degradation and still posts the review, because a review without
 * a preview is far more useful than no review at all.
 */
export async function runReviewPipeline({
  client,
  target,
  artifactsDir,
  superdocs,
  previewFormat = "docx",
  publicArtifactBaseUrl,
  now
}: {
  client: DocsReviewClient;
  target: PullRequestTarget;
  artifactsDir: string;
  superdocs?: SuperDocsClient;
  previewFormat?: SuperDocsExportFormat;
  publicArtifactBaseUrl?: string;
  now?: Clock;
}): Promise<ReviewPipelineResult> {
  const stages = new StageRecorder(now);

  const loaded = await stages.run("fetched_doc_files", () =>
    loadPullRequestDocs({
      client,
      owner: target.owner,
      repo: target.repo,
      pullNumber: target.pullNumber,
      headSha: target.headSha
    })
  );

  if (!loaded.ok) {
    return {
      status: "failed",
      target,
      skippedFiles: [],
      stages: stages.all(),
      totalMilliseconds: stages.totalMilliseconds(),
      detail: describeError(loaded.error)
    };
  }

  const docs = loaded.value.docs.map((doc) => doc.file);

  if (loaded.value.skipped.length > 0) {
    stages.markDegraded(
      "fetched_doc_files",
      `${loaded.value.skipped.length} changed file(s) could not be read and were skipped`
    );
  }

  if (docs.length === 0) {
    stages.note("ran_static_checks", "skipped", "no documentation files changed");

    return {
      status: "no-docs-changed",
      target,
      skippedFiles: loaded.value.skipped,
      stages: stages.all(),
      totalMilliseconds: stages.totalMilliseconds()
    };
  }

  const reviewed = await stages.run("ran_static_checks", () =>
    runStaticReview(docs)
  );

  if (!reviewed.ok) {
    return {
      status: "failed",
      target,
      skippedFiles: loaded.value.skipped,
      stages: stages.all(),
      totalMilliseconds: stages.totalMilliseconds(),
      detail: describeError(reviewed.error)
    };
  }

  const review = reviewed.value;

  const previewed = await stages.run("generated_preview", () =>
    generatePreview({
      target,
      docs: loaded.value.docs.map((doc) => ({
        ...doc.file,
        language: detectDocLanguage(doc.file.path)
      })),
      artifactsDir,
      client: superdocs,
      format: previewFormat,
      publicBaseUrl: publicArtifactBaseUrl
    })
  );

  if (!previewed.ok) {
    // The failed stage is already recorded. We keep going because a review
    // without a preview is more useful than no review at all.
  }

  const published = await stages.run("posted_review", () =>
    publishPullRequestReview({
      client,
      target,
      review,
      preview: previewed.ok ? previewLink(previewed.value.artifact) : undefined
    })
  );

  if (!published.ok) {
    return {
      status: "failed",
      target,
      review,
      preview: previewed.ok
        ? {
            mode: previewed.value.mode,
            url: previewed.value.artifact.url
          }
        : undefined,
      skippedFiles: loaded.value.skipped,
      stages: stages.all(),
      totalMilliseconds: stages.totalMilliseconds(),
      detail: describeError(published.error)
    };
  }

  stages.note("completed", "ok");

  return {
    status: "completed",
    target,
    review,
    published: published.value,
    preview: previewed.ok
      ? { mode: previewed.value.mode, url: previewed.value.artifact.url }
      : undefined,
    skippedFiles: loaded.value.skipped,
    stages: stages.all(),
    totalMilliseconds: stages.totalMilliseconds()
  };
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : "unknown error";
}
