import {
  formatInlineFindingBody,
  formatReviewBody,
  formatSummaryComment,
  reviewEventFor,
  summaryMarker,
  type PreviewArtifact,
  type PullRequestTarget
} from "./review-format.js";
import type { StaticReviewResult } from "../review/runner.js";

export type GitHubIssueComment = {
  id: number;
  body?: string;
      user?: {
        type?: string;
        login?: string;
      } | null;
    };

export type PullRequestReviewComment = {
  path: string;
  line: number;
  side: "RIGHT";
  body: string;
};

export type CreatePullRequestReviewInput = {
  owner: string;
  repo: string;
  pull_number: number;
  commit_id: string;
  event: "COMMENT" | "REQUEST_CHANGES";
  body: string;
  comments: PullRequestReviewComment[];
};

export type GitHubCommentClient = {
  listIssueComments(input: {
    owner: string;
    repo: string;
    issue_number: number;
  }): Promise<GitHubIssueComment[]>;
  createIssueComment(input: {
    owner: string;
    repo: string;
    issue_number: number;
    body: string;
  }): Promise<GitHubIssueComment>;
  updateIssueComment(input: {
    owner: string;
    repo: string;
    comment_id: number;
    body: string;
  }): Promise<GitHubIssueComment>;
};

export type GitHubReviewClient = GitHubCommentClient & {
  createPullRequestReview(input: CreatePullRequestReviewInput): Promise<{
    id: number;
  }>;
};

export type PublishReviewResult = {
  summaryComment: "created" | "updated";
  summaryCommentId: number;
  pullRequestReviewId: number;
  inlineCommentsPosted: number;
  event: "COMMENT" | "REQUEST_CHANGES";
};

export async function publishPullRequestReview({
  client,
  target,
  review,
  preview
}: {
  client: GitHubReviewClient;
  target: PullRequestTarget;
  review: StaticReviewResult;
  preview?: PreviewArtifact;
}): Promise<PublishReviewResult> {
  const summary = await upsertSummaryComment({ client, target, review, preview });
  const comments = buildInlineComments(review);
  const event = reviewEventFor(review.postedFindings);
  const pullRequestReview = await client.createPullRequestReview({
    owner: target.owner,
    repo: target.repo,
    pull_number: target.pullNumber,
    commit_id: target.headSha,
    event,
    body: formatReviewBody(review),
    comments
  });

  return {
    summaryComment: summary.action,
    summaryCommentId: summary.comment.id,
    pullRequestReviewId: pullRequestReview.id,
    inlineCommentsPosted: comments.length,
    event
  };
}

function buildInlineComments(review: StaticReviewResult): PullRequestReviewComment[] {
  return review.postedFindings.map((finding) => ({
    path: finding.path,
    line: finding.startLine,
    side: "RIGHT",
    body: formatInlineFindingBody(finding)
  }));
}

async function upsertSummaryComment({
  client,
  target,
  review,
  preview
}: {
  client: GitHubReviewClient;
  target: PullRequestTarget;
  review: StaticReviewResult;
  preview?: PreviewArtifact;
}) {
  const marker = summaryMarker(target.headSha);
  const body = formatSummaryComment({ target, review, preview });
  const existing = await findExistingSummaryComment(client, target, marker);

  if (existing) {
    const comment = await client.updateIssueComment({
      owner: target.owner,
      repo: target.repo,
      comment_id: existing.id,
      body
    });

    return {
      action: "updated" as const,
      comment
    };
  }

  const comment = await client.createIssueComment({
    owner: target.owner,
    repo: target.repo,
    issue_number: target.pullNumber,
    body
  });

  return {
    action: "created" as const,
    comment
  };
}

async function findExistingSummaryComment(
  client: GitHubReviewClient,
  target: PullRequestTarget,
  marker: string
): Promise<GitHubIssueComment | undefined> {
  const comments = await client.listIssueComments({
    owner: target.owner,
    repo: target.repo,
    issue_number: target.pullNumber
  });

  return comments.find((comment) => comment.body?.includes(marker));
}

