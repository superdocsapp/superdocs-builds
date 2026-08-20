import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { runApplyCommand } from "../commands/apply-runner.js";
import { parseCommand } from "../commands/parser.js";
import { loadConfig } from "../config.js";
import { runReviewPipeline } from "../pipeline/review-pipeline.js";
import { buildSuperDocsClient } from "../pipeline/dependencies.js";
import { createFakeRepository } from "./fake-repository.js";
import { demoPullRequestFiles } from "./fixtures.js";

/**
 * Runs the whole flow against an in-memory repository and prints what the app
 * would post. No credentials, no network, no installed GitHub App.
 */
export async function runDemo({
  artifactsDir,
  log = console.log
}: {
  artifactsDir: string;
  log?: (line: string) => void;
}): Promise<void> {
  const owner = "acme";
  const repo = "handbook";
  const pullNumber = 42;

  const { state, client } = createFakeRepository({
    owner,
    repo,
    pullNumber,
    headSha: "demo0000000",
    files: demoPullRequestFiles
  });

  heading(log, "1. A docs pull request arrives");
  log(`Repository: ${owner}/${repo}, pull request #${pullNumber}`);
  log(`Changed files: ${Object.keys(demoPullRequestFiles).join(", ")}`);

  heading(log, "2. The review runs");

  const config = loadConfig();
  const superdocs = buildSuperDocsClient(config, log);

  const target = {
    owner,
    repo,
    pullNumber,
    headSha: state.pullRequest.headSha
  };

  const result = await runReviewPipeline({
    client,
    target,
    artifactsDir,
    superdocs,
    publicArtifactBaseUrl: config.PUBLIC_ARTIFACT_BASE_URL
  });

  if (result.status !== "completed" || !result.review) {
    log(`The review did not complete: ${result.detail ?? result.status}`);
    return;
  }

  const { review } = result;

  log(`Files changed: ${review.summary.filesScanned}`);
  log(`Documentation files reviewed: ${review.summary.docsReviewed}`);
  log(`Findings generated: ${review.summary.findingsGenerated}`);
  log(`Findings posted: ${review.summary.findingsPosted}`);
  log(`Findings suppressed by the ranker: ${review.summary.findingsSuppressed}`);
  log(`Review event: ${result.published?.event ?? "unknown"}`);
  log(`Preview: ${result.preview?.mode ?? "not generated"} at ${result.preview?.url ?? "-"}`);

  heading(log, "3. What the app posted");

  for (const finding of review.postedFindings) {
    const fixable = finding.autofix ? "applicable" : "advisory only";
    log(
      `- [${finding.severity}] ${finding.path}:${finding.startLine} ${finding.title} (id ${finding.id}, ${fixable})`
    );
  }

  if (review.suppressedFindings.length > 0) {
    heading(log, "Held back to keep the review quiet");
    for (const finding of review.suppressedFindings) {
      log(`- ${finding.path}:${finding.startLine} ${finding.title}`);
    }
  }

  const applicable = review.postedFindings.filter((finding) => finding.autofix);
  const advisory = review.postedFindings.filter((finding) => !finding.autofix);

  if (applicable.length > 0) {
    const finding = applicable[0];

    heading(log, `4. A maintainer comments: /superdocs apply ${finding.id}`);

    const parsed = parseCommand(`/superdocs apply ${finding.id}`);
    if (!parsed.ok) {
      log(`The command did not parse: ${parsed.detail}`);
      return;
    }

    const applied = await runApplyCommand({
      client,
      owner,
      repo,
      pullNumber,
      requestedBy: "maintainer",
      target:
        parsed.command.verb === "apply"
          ? parsed.command.target.kind === "all-safe"
            ? { kind: "all-safe" }
            : { kind: "finding", findingId: parsed.command.target.findingId }
          : { kind: "all-safe" }
    });

    if (applied.status === "applied") {
      for (const commit of applied.commits) {
        log(`Committed ${commit.commitSha} to ${commit.path}`);
        log(`Lines changed: ${commit.changedLines.join(", ")}`);
        log(`Commit message: ${state.commits.at(-1)?.message.split("\n")[0]}`);
      }
    } else {
      log(`Not applied: ${describeOutcome(applied)}`);
    }

    heading(log, "5. The same command again, to show it never commits twice");

    // Two independent protections cover a repeated command, and which one fires
    // depends on timing. A duplicate webhook delivery arrives before the head SHA
    // moves and is stopped by the marker on the earlier reply; that case is
    // covered in tests. Here the commit has already landed, so the head SHA has
    // moved and the re-review is what stops it: the issue is simply gone.
    const repeated = await runApplyCommand({
      client,
      owner,
      repo,
      pullNumber,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId: finding.id }
    });

    log(`Outcome: ${repeated.status}`);
    log(`Reason: ${describeOutcome(repeated)}`);
    log(`Commits made in total: ${state.commits.length}`);
  }

  if (advisory.length > 0) {
    const finding = advisory[0];

    heading(
      log,
      `6. Asking it to fix something it should not guess: ${finding.id}`
    );
    log(`Finding: ${finding.title} at ${finding.path}:${finding.startLine}`);

    const refused = await runApplyCommand({
      client,
      owner,
      repo,
      pullNumber,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId: finding.id }
    });

    log(`Outcome: ${refused.status}`);
    log(`Reason: ${describeOutcome(refused)}`);
  }

  heading(log, "7. A reader without write access tries the same command");

  state.permission = "read";
  const unauthorized = await runApplyCommand({
    client,
    owner,
    repo,
    pullNumber,
    requestedBy: "passer-by",
    target: { kind: "all-safe" }
  });

  log(`Outcome: ${unauthorized.status}`);
  log(`Reason: ${describeOutcome(unauthorized)}`);

  heading(log, "8. Where the time went");
  for (const stage of result.stages) {
    log(
      `${stage.stage}: ${stage.status}${stage.detail ? ` (${stage.detail})` : ""} — ${stage.milliseconds}ms`
    );
  }
  log(`Total: ${result.totalMilliseconds}ms`);

  heading(log, "Artifacts");
  log(`Preview and review artifacts were written under ${artifactsDir}`);
}

function heading(log: (line: string) => void, text: string): void {
  log("");
  log(`== ${text}`);
}

function describeOutcome(outcome: {
  status: string;
  detail?: string;
  reason?: string;
}): string {
  return outcome.detail ?? outcome.reason ?? outcome.status;
}

if (process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]))) {
  const artifactsDir =
    process.env.ARTIFACTS_DIR ??
    (await mkdtemp(path.join(os.tmpdir(), "docs-pr-reviewer-demo-")));

  await runDemo({ artifactsDir });
}
