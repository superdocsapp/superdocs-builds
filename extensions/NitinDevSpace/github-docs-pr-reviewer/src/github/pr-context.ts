import type { ChangedFile, ChangedFileStatus } from "../review/scanner.js";
import { isDocumentationPath } from "../review/scanner.js";
import type { GitHubApplyClient } from "./apply-client.js";

export type LoadedDocFile = {
  file: ChangedFile;
  blobSha: string;
};

export type LoadedPullRequestDocs = {
  docs: LoadedDocFile[];
  changedFileCount: number;
  skipped: Array<{ path: string; reason: string }>;
};

/**
 * Loads the documentation files a pull request changed, with their content at the
 * given head commit. Content comes from the head SHA rather than the branch tip
 * so a review and a later apply agree on exactly which bytes they looked at.
 */
export async function loadPullRequestDocs({
  client,
  owner,
  repo,
  pullNumber,
  headSha
}: {
  client: GitHubApplyClient;
  owner: string;
  repo: string;
  pullNumber: number;
  headSha: string;
}): Promise<LoadedPullRequestDocs> {
  const changedFiles = await client.listPullRequestFiles({
    owner,
    repo,
    pull_number: pullNumber
  });

  const docs: LoadedDocFile[] = [];
  const skipped: Array<{ path: string; reason: string }> = [];

  for (const changed of changedFiles) {
    if (changed.status === "removed") continue;

    if (!isSafeRepositoryPath(changed.path)) {
      skipped.push({
        path: changed.path,
        reason: "path escapes the repository root"
      });
      continue;
    }

    if (!isDocumentationPath(changed.path)) continue;

    try {
      const blob = await client.getFile({
        owner,
        repo,
        path: changed.path,
        ref: headSha
      });

      docs.push({
        file: {
          path: changed.path,
          status: toChangedFileStatus(changed.status),
          additions: changed.additions,
          deletions: changed.deletions,
          patch: changed.patch,
          headContent: blob.content
        },
        blobSha: blob.blobSha
      });
    } catch (error) {
      skipped.push({
        path: changed.path,
        reason: error instanceof Error ? error.message : "could not be read"
      });
    }
  }

  return {
    docs,
    changedFileCount: changedFiles.length,
    skipped
  };
}

/**
 * Rejects paths that could point outside the repository. Paths arrive from
 * GitHub's own file list today, so this is defence in depth rather than the only
 * guard, and it holds if a path ever reaches here from somewhere less trusted.
 */
export function isSafeRepositoryPath(path: string): boolean {
  if (path === "" || path.startsWith("/") || path.includes("\\")) return false;
  if (/^[a-zA-Z]:/.test(path)) return false;

  return !path
    .split("/")
    .some((segment) => segment === ".." || segment === "" || segment === ".");
}

function toChangedFileStatus(status: string): ChangedFileStatus {
  const known: ChangedFileStatus[] = [
    "added",
    "modified",
    "removed",
    "renamed",
    "changed",
    "unchanged"
  ];

  return known.find((candidate) => candidate === status) ?? "modified";
}
