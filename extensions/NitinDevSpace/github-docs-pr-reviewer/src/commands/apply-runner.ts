import {
  canWriteToRepository,
  type GitHubApplyClient
} from "../github/apply-client.js";
import { loadPullRequestDocs, type LoadedDocFile } from "../github/pr-context.js";
import {
  isAutofixable,
  type AutofixableFinding,
  type Finding
} from "../review/findings.js";
import { applyLineAutofix, changedLineNumbers } from "../review/patches.js";
import { runStaticReview } from "../review/runner.js";
import {
  appliedMarker,
  formatAppliedReply,
  formatCommitMessage,
  formatRefusalReply,
  refusedMarker,
  type AppliedCommit
} from "./apply-format.js";

export type ApplyTarget =
  | { kind: "finding"; findingId: string }
  | { kind: "all-safe" };

export type ApplyRefusalReason =
  | "pull-request-not-open"
  | "insufficient-permission"
  | "fork-head-not-writable"
  | "finding-not-found"
  | "finding-not-autofixable"
  | "patch-no-longer-applies"
  | "patch-not-surgical"
  | "nothing-to-apply";

export type ApplyResult =
  | {
      status: "applied";
      headSha: string;
      commits: AppliedCommit[];
      replyCommentId: number;
    }
  | {
      status: "already-applied";
      headSha: string;
      existingCommentId: number;
    }
  | {
      status: "refused";
      reason: ApplyRefusalReason;
      detail: string;
      headSha?: string;
      replyCommentId?: number;
    }
  | {
      status: "failed";
      detail: string;
      headSha?: string;
      replyCommentId?: number;
    };

export type RunApplyCommandInput = {
  client: GitHubApplyClient;
  owner: string;
  repo: string;
  pullNumber: number;
  requestedBy: string;
  target: ApplyTarget;
};

export async function runApplyCommand({
  client,
  owner,
  repo,
  pullNumber,
  requestedBy,
  target
}: RunApplyCommandInput): Promise<ApplyResult> {
  const key = target.kind === "all-safe" ? "all-safe" : target.findingId;

  const context = await client.getPullRequest({
    owner,
    repo,
    pull_number: pullNumber
  });

  const permission = await client.getUserPermission({
    owner,
    repo,
    username: requestedBy
  });

  if (!canWriteToRepository(permission)) {
    return refuse({
      client,
      owner,
      repo,
      pullNumber,
      key,
      headSha: context.headSha,
      reason: "insufficient-permission",
      detail: `@${requestedBy} does not have write access to ${owner}/${repo}, so this command was not run.`,
      nextStep:
        "Ask someone with write access to run the command, or apply the suggestion from the review comment by hand."
    });
  }

  if (context.state !== "open") {
    return refuse({
      client,
      owner,
      repo,
      pullNumber,
      key,
      headSha: context.headSha,
      reason: "pull-request-not-open",
      detail: `This pull request is ${context.state}, so nothing was committed.`
    });
  }

  if (
    context.headRepoFullName !== "" &&
    context.headRepoFullName !== context.baseRepoFullName
  ) {
    return refuse({
      client,
      owner,
      repo,
      pullNumber,
      key,
      headSha: context.headSha,
      reason: "fork-head-not-writable",
      detail: `This pull request's head branch lives in \`${context.headRepoFullName}\`, and this app only commits to branches in \`${context.baseRepoFullName}\`.`,
      nextStep:
        "Copy the suggestion from the review comment, or push the change from the fork yourself."
    });
  }

  const existing = await findCommentWithMarker({
    client,
    owner,
    repo,
    pullNumber,
    marker: appliedMarker(key, context.headSha)
  });

  if (existing !== undefined) {
    return {
      status: "already-applied",
      headSha: context.headSha,
      existingCommentId: existing
    };
  }

  const loaded = await loadPullRequestDocs({
    client,
    owner,
    repo,
    pullNumber,
    headSha: context.headSha
  });

  const review = runStaticReview(loaded.docs.map((doc) => doc.file));
  const selected = selectFindings(review.findings, target);

  if (selected.length === 0) {
    return refuse({
      client,
      owner,
      repo,
      pullNumber,
      key,
      headSha: context.headSha,
      ...describeEmptySelection(review.findings, target)
    });
  }

  const notAutofixable = selected.filter((finding) => !isAutofixable(finding));

  if (target.kind === "finding" && notAutofixable.length > 0) {
    const finding = notAutofixable[0];

    return refuse({
      client,
      owner,
      repo,
      pullNumber,
      key,
      headSha: context.headSha,
      reason: "finding-not-autofixable",
      detail: `Finding \`${finding.id}\` (${finding.title}) has no mechanical fix, so this app will not guess one.`,
      nextStep: `Edit \`${finding.path}\` line ${finding.startLine} by hand. The review comment explains what to change.`
    });
  }

  const autofixable = selected.filter(isAutofixable);

  // Every file is patched and checked in memory before anything is written, so a
  // file that cannot be patched safely stops the whole command with the branch
  // still untouched, rather than leaving some files committed and some not.
  const planned: Array<{
    path: string;
    doc: LoadedDocFile;
    findings: AutofixableFinding[];
    content: string;
    changedLines: number[];
  }> = [];

  for (const [path, findings] of groupByPath(autofixable)) {
    const doc = loaded.docs.find((candidate) => candidate.file.path === path);

    if (!doc) {
      return refuse({
        client,
        owner,
        repo,
        pullNumber,
        key,
        headSha: context.headSha,
        reason: "patch-no-longer-applies",
        detail: `\`${path}\` could not be read at \`${context.headSha}\`, so nothing was committed.`
      });
    }

    const patched = applyFindingsToDocument(doc, findings);

    if (!patched.ok) {
      return refuse({
        client,
        owner,
        repo,
        pullNumber,
        key,
        headSha: context.headSha,
        reason: patched.reason,
        detail: patched.detail,
        nextStep: "Run `/superdocs review` to refresh findings against the current commit."
      });
    }

    planned.push({
      path,
      doc,
      findings,
      content: patched.content,
      changedLines: patched.changedLines
    });
  }

  const commits: AppliedCommit[] = [];

  for (const { path, doc, findings, content, changedLines } of planned) {
    try {
      const commit = await client.commitFile({
        owner,
        repo,
        path,
        branch: context.headRef,
        message: formatCommitMessage({ findings, requestedBy, path }),
        content,
        blobSha: doc.blobSha
      });

      commits.push({
        path,
        commitSha: commit.commitSha,
        commitUrl: commit.commitUrl,
        findingIds: findings.map((finding) => finding.id),
        changedLines
      });
    } catch (error) {
      const detail = error instanceof Error ? error.message : "unknown error";
      const reply = await client.createIssueComment({
        owner,
        repo,
        issue_number: pullNumber,
        body: formatRefusalReply({
          key,
          headSha: context.headSha,
          reason: "commit-rejected",
          detail: `GitHub rejected the commit to \`${path}\`: ${detail}`,
          nextStep: describePartialProgress(commits)
        })
      });

      return {
        status: "failed",
        detail,
        headSha: context.headSha,
        replyCommentId: reply.id
      };
    }
  }

  const reply = await client.createIssueComment({
    owner,
    repo,
    issue_number: pullNumber,
    body: formatAppliedReply({ key, headSha: context.headSha, commits })
  });

  return {
    status: "applied",
    headSha: context.headSha,
    commits,
    replyCommentId: reply.id
  };
}

type DocumentPatchResult =
  | { ok: true; content: string; changedLines: number[] }
  | { ok: false; reason: ApplyRefusalReason; detail: string };

/**
 * Applies every selected fix for one file to that file's content.
 *
 * Each fix is anchored to the exact line text the review saw, and the result is
 * checked against the original: if any line other than the targeted ones moved,
 * the whole file is refused rather than committed.
 */
function applyFindingsToDocument(
  doc: LoadedDocFile,
  findings: AutofixableFinding[]
): DocumentPatchResult {
  const original = doc.file.headContent ?? "";
  let content = original;
  const expectedLines = new Set<number>();

  for (const finding of findings) {
    const result = applyLineAutofix(content, finding.autofix);

    if (!result.ok) {
      return {
        ok: false,
        reason: "patch-no-longer-applies",
        detail: `Finding \`${finding.id}\` could not be applied to \`${doc.file.path}\`: ${result.detail}`
      };
    }

    content = result.content;
    expectedLines.add(finding.autofix.line);
  }

  const changedLines = changedLineNumbers(original, content);
  const unexpected = changedLines.filter((line) => !expectedLines.has(line));

  if (unexpected.length > 0) {
    return {
      ok: false,
      reason: "patch-not-surgical",
      detail: `Applying these fixes would also change line(s) ${unexpected.join(", ")} of \`${doc.file.path}\`, so nothing was committed.`
    };
  }

  return { ok: true, content, changedLines };
}

function selectFindings(findings: Finding[], target: ApplyTarget): Finding[] {
  if (target.kind === "all-safe") {
    return findings.filter(isAutofixable);
  }

  return findings.filter((finding) => finding.id === target.findingId);
}

function describeEmptySelection(
  findings: Finding[],
  target: ApplyTarget
): {
  reason: ApplyRefusalReason;
  detail: string;
  nextStep?: string;
} {
  if (target.kind === "all-safe") {
    return {
      reason: "nothing-to-apply",
      detail:
        findings.length === 0
          ? "There are no open documentation findings on this commit."
          : "None of the open findings have a mechanical fix, so there is nothing safe to apply automatically.",
      nextStep:
        findings.length === 0
          ? undefined
          : "The review comments explain each finding so you can fix them by hand."
    };
  }

  return {
    reason: "finding-not-found",
    detail: `Finding \`${target.findingId}\` is not present on the current commit. It may already be fixed, or the line may have moved.`,
    nextStep: "Run `/superdocs review` to get finding IDs for the current commit."
  };
}

function groupByPath<T extends Finding>(findings: T[]): Map<string, T[]> {
  const grouped = new Map<string, T[]>();

  for (const finding of findings) {
    const existing = grouped.get(finding.path);
    if (existing) {
      existing.push(finding);
      continue;
    }
    grouped.set(finding.path, [finding]);
  }

  return grouped;
}

function describePartialProgress(commits: AppliedCommit[]): string {
  if (commits.length === 0) {
    return "Nothing was committed, so the branch is unchanged.";
  }

  return `${commits.length} file(s) were already committed before this failure: ${commits
    .map((commit) => `\`${commit.path}\``)
    .join(", ")}. Re-run the command to finish the rest.`;
}

async function findCommentWithMarker({
  client,
  owner,
  repo,
  pullNumber,
  marker
}: {
  client: GitHubApplyClient;
  owner: string;
  repo: string;
  pullNumber: number;
  marker: string;
}): Promise<number | undefined> {
  const comments = await client.listIssueComments({
    owner,
    repo,
    issue_number: pullNumber
  });

  return comments.find((comment) => comment.body?.includes(marker))?.id;
}

/**
 * Explains why nothing was committed, once per reason per commit. Repeating a
 * command that cannot succeed should not add a new comment every time.
 */
async function refuse({
  client,
  owner,
  repo,
  pullNumber,
  key,
  headSha,
  reason,
  detail,
  nextStep
}: {
  client: GitHubApplyClient;
  owner: string;
  repo: string;
  pullNumber: number;
  key: string;
  headSha: string;
  reason: ApplyRefusalReason;
  detail: string;
  nextStep?: string;
}): Promise<ApplyResult> {
  const alreadyExplained = await findCommentWithMarker({
    client,
    owner,
    repo,
    pullNumber,
    marker: refusedMarker(key, headSha, reason)
  });

  if (alreadyExplained !== undefined) {
    return {
      status: "refused",
      reason,
      detail,
      headSha,
      replyCommentId: alreadyExplained
    };
  }

  const reply = await client.createIssueComment({
    owner,
    repo,
    issue_number: pullNumber,
    body: formatRefusalReply({ key, headSha, reason, detail, nextStep })
  });

  return {
    status: "refused",
    reason,
    detail,
    headSha,
    replyCommentId: reply.id
  };
}
