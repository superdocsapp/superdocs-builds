import { describe, expect, it, vi } from "vitest";
import { canWriteToRepository } from "../src/github/apply-client.js";
import { createOctokitApplyClient } from "../src/github/octokit-apply-client.js";
import type { GitHubCommentClient } from "../src/github/review-publisher.js";

const comments: GitHubCommentClient = {
  listIssueComments: vi.fn(async () => []),
  createIssueComment: vi.fn(async () => ({ id: 1 })),
  updateIssueComment: vi.fn(async () => ({ id: 1 }))
};

function createOctokit() {
  return {
    rest: {
      pulls: {
        get: vi.fn(async () => ({
          data: {
            number: 7,
            state: "open",
            head: {
              sha: "head-sha",
              ref: "docs-update",
              repo: { full_name: "octo/demo" }
            },
            base: { repo: { full_name: "octo/demo" } }
          }
        })),
        listFiles: vi.fn(async () => ({
          data: [
            { filename: "docs/guide.md", status: "modified", additions: 3 }
          ]
        }))
      },
      repos: {
        getCollaboratorPermissionLevel: vi.fn(async () => ({
          data: { permission: "write" }
        })),
        getContent: vi.fn(async () => ({
          data: {
            type: "file",
            encoding: "base64",
            sha: "blob-sha",
            content: Buffer.from("# Guide\n", "utf8").toString("base64")
          }
        })),
        createOrUpdateFileContents: vi.fn(async () => ({
          data: {
            commit: {
              sha: "commit-sha",
              html_url: "https://github.com/octo/demo/commit/commit-sha"
            }
          }
        }))
      }
    }
  };
}

describe("Octokit apply client adapter", () => {
  it("maps pull request context and file reads", async () => {
    const octokit = createOctokit();
    const client = createOctokitApplyClient(octokit, comments);

    await expect(
      client.getPullRequest({ owner: "octo", repo: "demo", pull_number: 7 })
    ).resolves.toEqual({
      pullNumber: 7,
      state: "open",
      headSha: "head-sha",
      headRef: "docs-update",
      headRepoFullName: "octo/demo",
      baseRepoFullName: "octo/demo"
    });

    await expect(
      client.listPullRequestFiles({ owner: "octo", repo: "demo", pull_number: 7 })
    ).resolves.toEqual([
      {
        path: "docs/guide.md",
        status: "modified",
        additions: 3,
        deletions: undefined,
        patch: undefined
      }
    ]);

    await expect(
      client.getFile({
        owner: "octo",
        repo: "demo",
        path: "docs/guide.md",
        ref: "head-sha"
      })
    ).resolves.toEqual({
      path: "docs/guide.md",
      content: "# Guide\n",
      blobSha: "blob-sha"
    });
  });

  it("base64-encodes content and passes the blob SHA when committing", async () => {
    const octokit = createOctokit();
    const client = createOctokitApplyClient(octokit, comments);

    await expect(
      client.commitFile({
        owner: "octo",
        repo: "demo",
        path: "docs/guide.md",
        branch: "docs-update",
        message: "docs: apply fix",
        content: "# Guide fixed\n",
        blobSha: "blob-sha"
      })
    ).resolves.toEqual({
      commitSha: "commit-sha",
      commitUrl: "https://github.com/octo/demo/commit/commit-sha"
    });

    expect(octokit.rest.repos.createOrUpdateFileContents).toHaveBeenCalledWith({
      owner: "octo",
      repo: "demo",
      path: "docs/guide.md",
      branch: "docs-update",
      message: "docs: apply fix",
      content: Buffer.from("# Guide fixed\n", "utf8").toString("base64"),
      sha: "blob-sha"
    });
  });

  it("refuses to treat a directory response as a patchable file", async () => {
    const octokit = createOctokit();
    octokit.rest.repos.getContent = vi.fn(async () => ({
      data: [{ type: "file", name: "guide.md" }]
    })) as never;

    const client = createOctokitApplyClient(octokit, comments);

    await expect(
      client.getFile({
        owner: "octo",
        repo: "demo",
        path: "docs",
        ref: "head-sha"
      })
    ).rejects.toThrow("not a regular file");
  });
});

describe("write permission check", () => {
  it("allows only permissions that can push", () => {
    expect(canWriteToRepository("admin")).toBe(true);
    expect(canWriteToRepository("maintain")).toBe(true);
    expect(canWriteToRepository("write")).toBe(true);
    expect(canWriteToRepository("WRITE")).toBe(true);
    expect(canWriteToRepository("triage")).toBe(false);
    expect(canWriteToRepository("read")).toBe(false);
    expect(canWriteToRepository("none")).toBe(false);
    expect(canWriteToRepository("")).toBe(false);
  });
});
