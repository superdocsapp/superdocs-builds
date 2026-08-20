import type { GitHubCommentClient } from "./review-publisher.js";

export type PullRequestContext = {
  pullNumber: number;
  state: string;
  headSha: string;
  headRef: string;
  headRepoFullName: string;
  baseRepoFullName: string;
};

export type PullRequestFile = {
  path: string;
  status: string;
  additions?: number;
  deletions?: number;
  patch?: string;
};

export type RepositoryFile = {
  path: string;
  content: string;
  /** Blob SHA, required by GitHub to update a file without clobbering it. */
  blobSha: string;
};

export type CommitFileResult = {
  commitSha: string;
  commitUrl?: string;
};

export type GitHubApplyClient = GitHubCommentClient & {
  getPullRequest(input: {
    owner: string;
    repo: string;
    pull_number: number;
  }): Promise<PullRequestContext>;
  listPullRequestFiles(input: {
    owner: string;
    repo: string;
    pull_number: number;
  }): Promise<PullRequestFile[]>;
  getUserPermission(input: {
    owner: string;
    repo: string;
    username: string;
  }): Promise<string>;
  getFile(input: {
    owner: string;
    repo: string;
    path: string;
    ref: string;
  }): Promise<RepositoryFile>;
  commitFile(input: {
    owner: string;
    repo: string;
    path: string;
    branch: string;
    message: string;
    content: string;
    blobSha: string;
  }): Promise<CommitFileResult>;
};

/** Permission levels GitHub reports that are allowed to change the branch. */
const writeCapablePermissions = new Set(["admin", "maintain", "write"]);

export function canWriteToRepository(permission: string): boolean {
  return writeCapablePermissions.has(permission.toLowerCase());
}
