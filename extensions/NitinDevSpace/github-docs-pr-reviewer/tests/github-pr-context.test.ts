import { describe, expect, it, vi } from "vitest";
import type { GitHubApplyClient } from "../src/github/apply-client.js";
import {
  isSafeRepositoryPath,
  loadPullRequestDocs
} from "../src/github/pr-context.js";

function createClient(
  files: Array<{ path: string; status?: string }>,
  contents: Record<string, string>
): GitHubApplyClient {
  return {
    listIssueComments: vi.fn(async () => []),
    createIssueComment: vi.fn(async () => ({ id: 1 })),
    updateIssueComment: vi.fn(async () => ({ id: 1 })),
    getPullRequest: vi.fn(),
    getUserPermission: vi.fn(),
    commitFile: vi.fn(),
    listPullRequestFiles: vi.fn(async () =>
      files.map((file) => ({ path: file.path, status: file.status ?? "modified" }))
    ),
    getFile: vi.fn(async ({ path }) => {
      const content = contents[path];
      if (content === undefined) throw new Error(`${path} not found`);
      return { path, content, blobSha: `blob-${path}` };
    })
  } as unknown as GitHubApplyClient;
}

describe("pull request doc loading", () => {
  it("keeps documentation files and drops code and deletions", async () => {
    const client = createClient(
      [
        { path: "docs/guide.md" },
        { path: "src/app.ts" },
        { path: "docs/removed.md", status: "removed" }
      ],
      { "docs/guide.md": "# Guide\n", "src/app.ts": "export {};" }
    );

    const loaded = await loadPullRequestDocs({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      headSha: "head-sha"
    });

    expect(loaded.changedFileCount).toBe(3);
    expect(loaded.docs.map((doc) => doc.file.path)).toEqual(["docs/guide.md"]);
    expect(loaded.docs[0].file.headContent).toBe("# Guide\n");
    expect(loaded.docs[0].blobSha).toBe("blob-docs/guide.md");
  });

  it("records a file it could not read instead of failing the run", async () => {
    const client = createClient([{ path: "docs/guide.md" }], {});

    const loaded = await loadPullRequestDocs({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      headSha: "head-sha"
    });

    expect(loaded.docs).toHaveLength(0);
    expect(loaded.skipped).toEqual([
      { path: "docs/guide.md", reason: "docs/guide.md not found" }
    ]);
  });

  it("skips a path that escapes the repository root", async () => {
    const client = createClient([{ path: "docs/../../etc/passwd.md" }], {
      "docs/../../etc/passwd.md": "malicious"
    });

    const loaded = await loadPullRequestDocs({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      headSha: "head-sha"
    });

    expect(loaded.docs).toHaveLength(0);
    expect(loaded.skipped[0].reason).toBe("path escapes the repository root");
    expect(client.getFile).not.toHaveBeenCalled();
  });
});

describe("repository path guard", () => {
  it("accepts ordinary repository paths", () => {
    expect(isSafeRepositoryPath("README.md")).toBe(true);
    expect(isSafeRepositoryPath("docs/guide.md")).toBe(true);
    expect(isSafeRepositoryPath("docs/deep/nested-file.mdx")).toBe(true);
  });

  it("rejects traversal, absolute, and drive paths", () => {
    expect(isSafeRepositoryPath("../secrets.md")).toBe(false);
    expect(isSafeRepositoryPath("docs/../../etc/passwd")).toBe(false);
    expect(isSafeRepositoryPath("/etc/passwd")).toBe(false);
    expect(isSafeRepositoryPath("C:/Windows/system.md")).toBe(false);
    expect(isSafeRepositoryPath("docs\\guide.md")).toBe(false);
    expect(isSafeRepositoryPath("docs//guide.md")).toBe(false);
    expect(isSafeRepositoryPath("./guide.md")).toBe(false);
    expect(isSafeRepositoryPath("")).toBe(false);
  });
});
