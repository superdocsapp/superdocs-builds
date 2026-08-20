import { describe, expect, it, vi } from "vitest";
import { createOctokitReviewClient } from "../src/github/octokit-review-client.js";

describe("Octokit review client adapter", () => {
  it("maps publisher calls to Octokit REST calls", async () => {
    const octokit = {
      rest: {
        issues: {
          listComments: vi.fn(async () => ({ data: [{ id: 1, body: "hello" }] })),
          createComment: vi.fn(async (input) => ({
            data: { id: 2, body: input.body }
          })),
          updateComment: vi.fn(async (input) => ({
            data: { id: input.comment_id, body: input.body }
          }))
        },
        pulls: {
          createReview: vi.fn(async () => ({ data: { id: 3 } }))
        }
      }
    };

    const client = createOctokitReviewClient(octokit);

    await expect(
      client.listIssueComments({
        owner: "octo",
        repo: "demo",
        issue_number: 7
      })
    ).resolves.toEqual([{ id: 1, body: "hello" }]);

    await expect(
      client.createIssueComment({
        owner: "octo",
        repo: "demo",
        issue_number: 7,
        body: "summary"
      })
    ).resolves.toEqual({ id: 2, body: "summary" });

    await expect(
      client.updateIssueComment({
        owner: "octo",
        repo: "demo",
        comment_id: 2,
        body: "updated"
      })
    ).resolves.toEqual({ id: 2, body: "updated" });

    await expect(
      client.createPullRequestReview({
        owner: "octo",
        repo: "demo",
        pull_number: 7,
        commit_id: "abc123",
        event: "COMMENT",
        body: "review",
        comments: []
      })
    ).resolves.toEqual({ id: 3 });

    expect(octokit.rest.issues.listComments).toHaveBeenCalledWith({
      owner: "octo",
      repo: "demo",
      issue_number: 7,
      per_page: 100
    });
  });
});

