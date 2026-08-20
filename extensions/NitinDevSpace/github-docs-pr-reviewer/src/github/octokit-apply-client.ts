import type {
  CommitFileResult,
  GitHubApplyClient,
  PullRequestContext,
  PullRequestFile,
  RepositoryFile
} from "./apply-client.js";
import type { GitHubCommentClient } from "./review-publisher.js";

type OctokitApplyLike = {
  rest: {
    pulls: {
      get(input: { owner: string; repo: string; pull_number: number }): Promise<{
        data: {
          number: number;
          state: string;
          head: {
            sha: string;
            ref: string;
            repo?: { full_name?: string } | null;
          };
          base: {
            repo?: { full_name?: string } | null;
          };
        };
      }>;
      listFiles(input: {
        owner: string;
        repo: string;
        pull_number: number;
        per_page?: number;
      }): Promise<{
        data: Array<{
          filename: string;
          status: string;
          additions?: number;
          deletions?: number;
          patch?: string;
        }>;
      }>;
    };
    repos: {
      getCollaboratorPermissionLevel(input: {
        owner: string;
        repo: string;
        username: string;
      }): Promise<{ data: { permission: string } }>;
      getContent(input: {
        owner: string;
        repo: string;
        path: string;
        ref: string;
      }): Promise<{ data: unknown }>;
      createOrUpdateFileContents(input: {
        owner: string;
        repo: string;
        path: string;
        branch: string;
        message: string;
        content: string;
        sha: string;
      }): Promise<{
        data: { commit: { sha?: string; html_url?: string } };
      }>;
    };
  };
};

export function createOctokitApplyClient(
  octokit: OctokitApplyLike,
  comments: GitHubCommentClient
): GitHubApplyClient {
  return {
    ...comments,

    async getPullRequest(input): Promise<PullRequestContext> {
      const { data } = await octokit.rest.pulls.get(input);

      return {
        pullNumber: data.number,
        state: data.state,
        headSha: data.head.sha,
        headRef: data.head.ref,
        headRepoFullName: data.head.repo?.full_name ?? "",
        baseRepoFullName:
          data.base.repo?.full_name ?? `${input.owner}/${input.repo}`
      };
    },

    async listPullRequestFiles(input): Promise<PullRequestFile[]> {
      const { data } = await octokit.rest.pulls.listFiles({
        ...input,
        per_page: 100
      });

      return data.map((file) => ({
        path: file.filename,
        status: file.status,
        additions: file.additions,
        deletions: file.deletions,
        patch: file.patch
      }));
    },

    async getUserPermission(input): Promise<string> {
      const { data } = await octokit.rest.repos.getCollaboratorPermissionLevel(
        input
      );
      return data.permission;
    },

    async getFile(input): Promise<RepositoryFile> {
      const { data } = await octokit.rest.repos.getContent(input);

      if (!isFileContentResponse(data)) {
        throw new Error(
          `${input.path} is not a regular file at ${input.ref}, so it cannot be patched.`
        );
      }

      return {
        path: input.path,
        content: Buffer.from(data.content, "base64").toString("utf8"),
        blobSha: data.sha
      };
    },

    async commitFile(input): Promise<CommitFileResult> {
      const { data } = await octokit.rest.repos.createOrUpdateFileContents({
        owner: input.owner,
        repo: input.repo,
        path: input.path,
        branch: input.branch,
        message: input.message,
        content: Buffer.from(input.content, "utf8").toString("base64"),
        sha: input.blobSha
      });

      return {
        commitSha: data.commit.sha ?? "",
        commitUrl: data.commit.html_url
      };
    }
  };
}

function isFileContentResponse(
  data: unknown
): data is { type: string; content: string; sha: string; encoding: string } {
  if (typeof data !== "object" || data === null) return false;

  const candidate = data as Record<string, unknown>;

  return (
    candidate.type === "file" &&
    typeof candidate.content === "string" &&
    typeof candidate.sha === "string"
  );
}
