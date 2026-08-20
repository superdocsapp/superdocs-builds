import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { PreviewArtifact, PullRequestTarget } from "../github/review-format.js";

export type StoredPreviewArtifact = PreviewArtifact & {
  filePath: string;
  contentType: string;
};

export async function storePreviewArtifact({
  artifactsDir,
  target,
  filename,
  data,
  contentType,
  publicBaseUrl
}: {
  artifactsDir: string;
  target: PullRequestTarget;
  filename: string;
  data: Uint8Array;
  contentType: string;
  publicBaseUrl?: string;
}): Promise<StoredPreviewArtifact> {
  return storeArtifact({
    artifactsDir,
    relativeDirectory: path.posix.join(
      "previews",
      safeSegment(target.owner),
      safeSegment(target.repo),
      `pr-${target.pullNumber}`,
      safeSegment(target.headSha).slice(0, 12)
    ),
    filename,
    data,
    contentType,
    publicBaseUrl
  });
}

/**
 * Writes one artifact under the artifacts directory and reports where it landed.
 * Every path segment is sanitised, so a tag or branch name can never write outside
 * the artifacts directory.
 */
export async function storeArtifact({
  artifactsDir,
  relativeDirectory,
  filename,
  data,
  contentType,
  publicBaseUrl
}: {
  artifactsDir: string;
  relativeDirectory: string;
  filename: string;
  data: Uint8Array;
  contentType: string;
  publicBaseUrl?: string;
}): Promise<StoredPreviewArtifact> {
  const directory = path.join(artifactsDir, ...relativeDirectory.split("/"));
  const safeFilename = safeSegment(filename);
  const filePath = path.join(directory, safeFilename);

  await mkdir(directory, { recursive: true });
  await writeFile(filePath, data);

  const url = publicBaseUrl
    ? `${publicBaseUrl.replace(/\/$/, "")}/${relativeDirectory}/${safeFilename}`
    : filePath;

  return {
    url,
    label: `Open ${safeFilename}`,
    filePath,
    contentType
  };
}

export { safeSegment };

/**
 * Reduces an untrusted value to one safe path segment.
 *
 * Dots are allowed so filenames keep their extensions, which means a value made
 * only of dots (`.` or `..`) would otherwise survive as a real traversal segment.
 * Those are replaced outright rather than filtered character by character.
 */
function safeSegment(value: string): string {
  const cleaned = value
    .replace(/[^a-zA-Z0-9._-]/g, "-")
    .replace(/^[-.]+|-+$/g, "");

  if (cleaned === "" || /^\.+$/.test(cleaned)) return "unknown";

  return cleaned;
}
