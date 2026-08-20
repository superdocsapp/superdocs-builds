import type {
  CommitFileResult,
  GitHubApplyClient,
  PullRequestContext,
  PullRequestFile,
  RepositoryFile
} from "../github/apply-client.js";
import type {
  CreatePullRequestReviewInput,
  GitHubIssueComment
} from "../github/review-publisher.js";
import type { DocsReviewClient } from "../pipeline/review-pipeline.js";

export type FakeRepositoryState = {
  files: Map<string, string>;
  comments: GitHubIssueComment[];
  reviews: CreatePullRequestReviewInput[];
  commits: Array<{ path: string; message: string; content: string }>;
  permission: string;
  pullRequest: PullRequestContext;
};

/**
 * An in-memory stand-in for one GitHub repository.
 *
 * The demo and several tests drive the real pipeline against this instead of the
 * GitHub API, so the whole flow can be run and inspected with no credentials, no
 * network, and no installed app.
 */
export function createFakeRepository({
  owner,
  repo,
  pullNumber,
  headSha,
  headRef = "docs-update",
  files,
  permission = "write"
}: {
  owner: string;
  repo: string;
  pullNumber: number;
  headSha: string;
  headRef?: string;
  files: Record<string, string>;
  permission?: string;
}): { state: FakeRepositoryState; client: DocsReviewClient } {
  const state: FakeRepositoryState = {
    files: new Map(Object.entries(files)),
    comments: [],
    reviews: [],
    commits: [],
    permission,
    pullRequest: {
      pullNumber,
      state: "open",
      headSha,
      headRef,
      headRepoFullName: `${owner}/${repo}`,
      baseRepoFullName: `${owner}/${repo}`
    }
  };

  let nextCommentId = 1000;
  let nextReviewId = 2000;
  let commitCounter = 0;

  const client: DocsReviewClient = {
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
      if (!comment) throw new Error(`comment ${comment_id} not found`);
      comment.body = body;
      return comment;
    },

    async createPullRequestReview(input) {
      state.reviews.push(input);
      return { id: (nextReviewId += 1) };
    },

    async getPullRequest(): Promise<PullRequestContext> {
      return state.pullRequest;
    },

    async listPullRequestFiles(): Promise<PullRequestFile[]> {
      return [...state.files.keys()].map((path) => ({
        path,
        status: "modified"
      }));
    },

    async getUserPermission(): Promise<string> {
      return state.permission;
    },

    async getFile({ path }): Promise<RepositoryFile> {
      const content = state.files.get(path);
      if (content === undefined) throw new Error(`${path} not found`);
      return { path, content, blobSha: blobShaFor(path, content) };
    },

    async commitFile(input): Promise<CommitFileResult> {
      const current = state.files.get(input.path);

      if (current === undefined) {
        throw new Error(`${input.path} not found`);
      }

      if (blobShaFor(input.path, current) !== input.blobSha) {
        throw new Error(
          `409 Conflict: ${input.path} changed since it was read`
        );
      }

      state.files.set(input.path, input.content);
      state.commits.push({
        path: input.path,
        message: input.message,
        content: input.content
      });
      commitCounter += 1;

      const commitSha = `demo${String(commitCounter).padStart(7, "0")}`;
      state.pullRequest = { ...state.pullRequest, headSha: commitSha };

      return { commitSha };
    }
  };

  return { state, client };
}

/**
 * A content-derived stand-in for a git blob SHA, so the fake rejects a stale write
 * exactly the way GitHub's contents API does.
 */
function blobShaFor(path: string, content: string): string {
  let hash = 0;

  for (const character of `${path}:${content}`) {
    hash = (hash * 31 + character.codePointAt(0)!) | 0;
  }

  return `blob-${(hash >>> 0).toString(16)}`;
}
