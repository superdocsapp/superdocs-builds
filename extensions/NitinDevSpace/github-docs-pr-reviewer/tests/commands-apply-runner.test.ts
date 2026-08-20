import { describe, expect, it } from "vitest";
import { runApplyCommand } from "../src/commands/apply-runner.js";
import type {
  GitHubApplyClient,
  PullRequestContext,
  PullRequestFile
} from "../src/github/apply-client.js";
import type { GitHubIssueComment } from "../src/github/review-publisher.js";
import { runStaticReview } from "../src/review/runner.js";

type FakeState = {
  permission: string;
  pullRequest: PullRequestContext;
  files: Map<string, { content: string; blobSha: string }>;
  comments: GitHubIssueComment[];
  commits: Array<{
    path: string;
    branch: string;
    message: string;
    content: string;
    blobSha: string;
  }>;
  failCommitWith?: string;
};

const styleDoc = "# Guide\n\nUtilize the API to get started.\n";
const twoFixDoc = "# Title\n\n### Details\n\nUtilize the API.\n";
const advisoryDoc = "# Notes\n\nRelease date: TBD\n";

function createFake(
  overrides: Partial<FakeState> & { docs?: Record<string, string> } = {}
) {
  const docs = overrides.docs ?? { "docs/guide.md": styleDoc };

  const state: FakeState = {
    permission: "write",
    pullRequest: {
      pullNumber: 7,
      state: "open",
      headSha: "head-sha-1",
      headRef: "docs-update",
      headRepoFullName: "octo/demo",
      baseRepoFullName: "octo/demo"
    },
    files: new Map(
      Object.entries(docs).map(([path, content], index) => [
        path,
        { content, blobSha: `blob-${index}` }
      ])
    ),
    comments: [],
    commits: [],
    ...overrides
  };

  const prFiles: PullRequestFile[] = Object.keys(docs).map((path) => ({
    path,
    status: "modified"
  }));

  let nextCommentId = 100;

  const client: GitHubApplyClient = {
    async listIssueComments() {
      return state.comments;
    },
    async createIssueComment({ body }) {
      const comment = { id: (nextCommentId += 1), body };
      state.comments.push(comment);
      return comment;
    },
    async updateIssueComment({ comment_id, body }) {
      const comment = state.comments.find((entry) => entry.id === comment_id);
      if (!comment) throw new Error("comment not found");
      comment.body = body;
      return comment;
    },
    async getPullRequest() {
      return state.pullRequest;
    },
    async listPullRequestFiles() {
      return prFiles;
    },
    async getUserPermission() {
      return state.permission;
    },
    async getFile({ path }) {
      const file = state.files.get(path);
      if (!file) throw new Error(`${path} not found`);
      return { path, content: file.content, blobSha: file.blobSha };
    },
    async commitFile(input) {
      if (state.failCommitWith) {
        throw new Error(state.failCommitWith);
      }

      state.commits.push({
        path: input.path,
        branch: input.branch,
        message: input.message,
        content: input.content,
        blobSha: input.blobSha
      });
      state.files.set(input.path, {
        content: input.content,
        blobSha: `${input.blobSha}-next`
      });

      return {
        commitSha: `commit-sha-${state.commits.length}`,
        commitUrl: `https://github.com/octo/demo/commit/commit-sha-${state.commits.length}`
      };
    }
  };

  return { state, client };
}

/** Finding IDs are content-derived, so tests discover them the way a maintainer does. */
function findingIdFor(path: string, content: string, title: string): string {
  const review = runStaticReview([{ path, status: "modified", headContent: content }]);
  const finding = review.findings.find((entry) => entry.title === title);
  if (!finding) throw new Error(`no finding titled ${title}`);
  return finding.id;
}

function lastCommentBody(state: FakeState): string {
  return state.comments[state.comments.length - 1]?.body ?? "";
}

describe("apply command", () => {
  it("applies one safe fix as a single commit and changes only that line", async () => {
    const { state, client } = createFake();
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(result.status).toBe("applied");
    if (result.status !== "applied") return;

    expect(state.commits).toHaveLength(1);
    expect(state.commits[0].branch).toBe("docs-update");
    expect(state.commits[0].content).toBe(
      "# Guide\n\nUse the API to get started.\n"
    );
    expect(result.commits[0].changedLines).toEqual([3]);
    expect(lastCommentBody(state)).toContain("Applied.");
  });

  it("attributes the commit to the requester and the finding", async () => {
    const { state, client } = createFake();
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(state.commits[0].message).toContain(findingId);
    expect(state.commits[0].message).toContain("@maintainer");
  });

  it("refuses a requester without write access and commits nothing", async () => {
    const { state, client } = createFake({ permission: "read" });
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "drive-by",
      target: { kind: "finding", findingId }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "insufficient-permission"
    });
    expect(state.commits).toHaveLength(0);
    expect(lastCommentBody(state)).toContain("does not have write access");
  });

  it("does not commit twice for the same command on the same head commit", async () => {
    const { state, client } = createFake();
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");
    const input = {
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding" as const, findingId }
    };

    const first = await runApplyCommand(input);
    const second = await runApplyCommand(input);

    expect(first.status).toBe("applied");
    expect(second.status).toBe("already-applied");
    expect(state.commits).toHaveLength(1);
  });

  it("refuses a finding ID that is not on the current commit", async () => {
    const { state, client } = createFake();

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId: "0123456789" }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "finding-not-found"
    });
    expect(state.commits).toHaveLength(0);
    expect(lastCommentBody(state)).toContain("/superdocs review");
  });

  it("refuses to guess a fix for an advisory finding", async () => {
    const { state, client } = createFake({
      docs: { "docs/notes.md": advisoryDoc }
    });
    const findingId = findingIdFor(
      "docs/notes.md",
      advisoryDoc,
      "Unresolved placeholder"
    );

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "finding-not-autofixable"
    });
    expect(state.commits).toHaveLength(0);
  });

  it("does not commit to a fork head branch", async () => {
    const { state, client } = createFake({
      pullRequest: {
        pullNumber: 7,
        state: "open",
        headSha: "head-sha-1",
        headRef: "docs-update",
        headRepoFullName: "contributor/demo",
        baseRepoFullName: "octo/demo"
      }
    });
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "fork-head-not-writable"
    });
    expect(state.commits).toHaveLength(0);
  });

  it("does not commit to a closed pull request", async () => {
    const { state, client } = createFake({
      pullRequest: {
        pullNumber: 7,
        state: "closed",
        headSha: "head-sha-1",
        headRef: "docs-update",
        headRepoFullName: "octo/demo",
        baseRepoFullName: "octo/demo"
      }
    });
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "pull-request-not-open"
    });
    expect(state.commits).toHaveLength(0);
  });

  it("explains a repeated impossible command only once", async () => {
    const { state, client } = createFake({ permission: "read" });
    const input = {
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "drive-by",
      target: { kind: "finding" as const, findingId: "0123456789" }
    };

    await runApplyCommand(input);
    await runApplyCommand(input);

    expect(state.comments).toHaveLength(1);
  });

  it("applies every safe fix in a file as one commit", async () => {
    const { state, client } = createFake({
      docs: { "docs/guide.md": twoFixDoc }
    });

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "all-safe" }
    });

    expect(result.status).toBe("applied");
    if (result.status !== "applied") return;

    expect(state.commits).toHaveLength(1);
    expect(state.commits[0].content).toBe(
      "# Title\n\n## Details\n\nUse the API.\n"
    );
    expect(result.commits[0].changedLines).toEqual([3, 5]);
  });

  it("reports honestly when there is nothing safe to apply", async () => {
    const { state, client } = createFake({
      docs: { "docs/notes.md": advisoryDoc }
    });

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "all-safe" }
    });

    expect(result).toMatchObject({
      status: "refused",
      reason: "nothing-to-apply"
    });
    expect(state.commits).toHaveLength(0);
  });

  it("reports a rejected commit instead of claiming success", async () => {
    const { state, client } = createFake({
      failCommitWith: "409 Conflict: the branch moved"
    });
    const findingId = findingIdFor("docs/guide.md", styleDoc, "Style guide wording");

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "finding", findingId }
    });

    expect(result).toMatchObject({ status: "failed" });
    expect(state.commits).toHaveLength(0);
    expect(lastCommentBody(state)).toContain("Not applied.");
    expect(lastCommentBody(state)).toContain("409 Conflict");
  });

  it("still applies the readable files when one file cannot be read", async () => {
    const { state, client } = createFake({
      docs: { "docs/a.md": styleDoc, "docs/b.md": twoFixDoc }
    });

    const readFile = client.getFile;
    client.getFile = async (input) => {
      if (input.path === "docs/b.md") throw new Error("docs/b.md not found");
      return readFile(input);
    };

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "all-safe" }
    });

    expect(result.status).toBe("applied");
    expect(state.commits.map((commit) => commit.path)).toEqual(["docs/a.md"]);
  });

  it("names what was already committed when a later commit is rejected", async () => {
    const { state, client } = createFake({
      docs: { "docs/a.md": styleDoc, "docs/b.md": twoFixDoc }
    });

    const commitFile = client.commitFile;
    client.commitFile = async (input) => {
      if (input.path === "docs/b.md") {
        throw new Error("409 Conflict: the branch moved");
      }
      return commitFile(input);
    };

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "all-safe" }
    });

    expect(result.status).toBe("failed");
    expect(state.commits.map((commit) => commit.path)).toEqual(["docs/a.md"]);
    expect(lastCommentBody(state)).toContain("Not applied.");
    expect(lastCommentBody(state)).toContain("docs/a.md");
    expect(lastCommentBody(state)).toContain("already committed");
  });

  it("ignores non-documentation files when resolving findings", async () => {
    const { state, client } = createFake({
      docs: { "docs/guide.md": styleDoc, "src/app.ts": "// Utilize the API\n" }
    });

    const result = await runApplyCommand({
      client,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      target: { kind: "all-safe" }
    });

    expect(result.status).toBe("applied");
    expect(state.commits.map((commit) => commit.path)).toEqual([
      "docs/guide.md"
    ]);
  });
});
