import { describe, expect, it, vi } from "vitest";
import {
  publishPullRequestReview,
  type GitHubIssueComment,
  type GitHubReviewClient
} from "../src/github/review-publisher.js";
import { createFinding } from "../src/review/findings.js";
import type { StaticReviewResult } from "../src/review/runner.js";

function makeReviewResult(count = 1, severity: "blocker" | "warning" = "warning"): StaticReviewResult {
  const findings = Array.from({ length: count }, (_, index) =>
    createFinding({
      severity,
      category: severity === "blocker" ? "style" : "structure",
      path: "README.md",
      startLine: index + 1,
      title: severity === "blocker" ? "Unresolved placeholder" : "Heading level skips",
      explanation: "Review this line.",
      confidence: "high",
      source: "rule"
    })
  );

  return {
    docs: [],
    findings,
    postedFindings: findings.slice(0, 5),
    suppressedFindings: findings.slice(5),
    summary: {
      filesScanned: 1,
      docsReviewed: 1,
      findingsGenerated: findings.length,
      findingsPosted: Math.min(findings.length, 5),
      findingsSuppressed: Math.max(findings.length - 5, 0)
    }
  };
}

function fakeClient(existingComments: GitHubIssueComment[] = []): GitHubReviewClient {
  return {
    listIssueComments: vi.fn(async () => existingComments),
    createIssueComment: vi.fn(async (_input) => ({
      id: 10,
      body: _input.body
    })),
    updateIssueComment: vi.fn(async (_input) => ({
      id: _input.comment_id,
      body: _input.body
    })),
    createPullRequestReview: vi.fn(async () => ({
      id: 99
    }))
  };
}

const target = {
  owner: "octo",
  repo: "demo",
  pullNumber: 7,
  headSha: "abc123"
};

describe("GitHub review publisher", () => {
  it("creates a summary comment and pull request review", async () => {
    const client = fakeClient();
    const result = await publishPullRequestReview({
      client,
      target,
      review: makeReviewResult(2)
    });

    expect(result).toEqual({
      summaryComment: "created",
      summaryCommentId: 10,
      pullRequestReviewId: 99,
      inlineCommentsPosted: 2,
      event: "COMMENT"
    });
    expect(client.createIssueComment).toHaveBeenCalledOnce();
    expect(client.createPullRequestReview).toHaveBeenCalledWith(
      expect.objectContaining({
        owner: "octo",
        repo: "demo",
        pull_number: 7,
        commit_id: "abc123",
        event: "COMMENT",
        comments: expect.arrayContaining([
          expect.objectContaining({
            path: "README.md",
            line: 1,
            side: "RIGHT"
          })
        ])
      })
    );
  });

  it("updates an existing summary comment for the same head sha", async () => {
    const client = fakeClient([
      {
        id: 44,
        body: "<!-- superdocs-docs-pr-reviewer:abc123 -->\nold"
      }
    ]);

    const result = await publishPullRequestReview({
      client,
      target,
      review: makeReviewResult(1)
    });

    expect(result.summaryComment).toBe("updated");
    expect(result.summaryCommentId).toBe(44);
    expect(client.updateIssueComment).toHaveBeenCalledOnce();
    expect(client.createIssueComment).not.toHaveBeenCalled();
  });

  it("includes the generated preview link in the summary", async () => {
    const client = fakeClient();

    await publishPullRequestReview({
      client,
      target,
      review: makeReviewResult(0),
      preview: {
        url: "https://artifacts.example/preview.pdf",
        label: "Open preview.pdf"
      }
    });

    expect(client.createIssueComment).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("[Open preview.pdf](https://artifacts.example/preview.pdf)")
      })
    );
  });

  it("requests changes when posted findings include blockers", async () => {
    const client = fakeClient();
    const result = await publishPullRequestReview({
      client,
      target,
      review: makeReviewResult(1, "blocker")
    });

    expect(result.event).toBe("REQUEST_CHANGES");
    expect(client.createPullRequestReview).toHaveBeenCalledWith(
      expect.objectContaining({
        event: "REQUEST_CHANGES"
      })
    );
  });
});
