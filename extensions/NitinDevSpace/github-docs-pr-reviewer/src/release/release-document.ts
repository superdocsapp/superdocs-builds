import type {
  GitHubReleaseClient,
  ReleaseTarget
} from "../github/release-client.js";
import { safeSegment, storeArtifact } from "../preview/artifacts.js";
import type { StoredPreviewArtifact } from "../preview/artifacts.js";
import type {
  SuperDocsClient,
  SuperDocsExportFormat
} from "../superdocs/client.js";
import {
  collectReleaseSources,
  releaseDocumentTitle,
  renderReleaseDocumentHtml,
  type ReleaseDocumentSources
} from "./release-notes.js";

export type ReleaseDocumentResult = {
  status: "attached" | "already-attached" | "stored-only";
  assetName: string;
  artifact: StoredPreviewArtifact;
  mode: "superdocs" | "local-html";
  sources: ReleaseDocumentSources;
  /** Present when the document was generated but could not be attached. */
  attachError?: string;
};

export async function generateReleaseDocument({
  client,
  target,
  artifactsDir,
  superdocs,
  format = "docx",
  publicBaseUrl
}: {
  client: GitHubReleaseClient;
  target: ReleaseTarget;
  artifactsDir: string;
  superdocs?: SuperDocsClient;
  format?: SuperDocsExportFormat;
  publicBaseUrl?: string;
}): Promise<ReleaseDocumentResult> {
  const sources = await collectReleaseSources({ client, target });
  const html = renderReleaseDocumentHtml(sources);

  const exported = await exportReleaseDocument({
    superdocs,
    target,
    html,
    format
  });

  const assetName = `release-notes-${safeSegment(target.tagName)}.${exported.extension}`;

  const artifact = await storeArtifact({
    artifactsDir,
    relativeDirectory: ["releases", safeSegment(target.owner), safeSegment(target.repo), safeSegment(target.tagName)].join("/"),
    filename: assetName,
    data: exported.data,
    contentType: exported.contentType,
    publicBaseUrl
  });

  const existing = await findExistingAsset({ client, target, assetName });

  if (existing) {
    return {
      status: "already-attached",
      assetName,
      artifact,
      mode: exported.mode,
      sources
    };
  }

  try {
    await client.uploadReleaseAsset({
      owner: target.owner,
      repo: target.repo,
      release_id: target.releaseId,
      name: assetName,
      contentType: exported.contentType,
      data: exported.data
    });
  } catch (error) {
    return {
      status: "stored-only",
      assetName,
      artifact,
      mode: exported.mode,
      sources,
      attachError: error instanceof Error ? error.message : "unknown error"
    };
  }

  return {
    status: "attached",
    assetName,
    artifact,
    mode: exported.mode,
    sources
  };
}

type ExportedReleaseDocument = {
  data: Uint8Array;
  contentType: string;
  extension: string;
  mode: "superdocs" | "local-html";
};

/**
 * Exports through SuperDocs when a key is configured, and falls back to the same
 * HTML as a local artifact when it is not or when the export fails. The fallback
 * uses the identical source HTML, so the preview and the export never diverge.
 */
async function exportReleaseDocument({
  superdocs,
  target,
  html,
  format
}: {
  superdocs?: SuperDocsClient;
  target: ReleaseTarget;
  html: string;
  format: SuperDocsExportFormat;
}): Promise<ExportedReleaseDocument> {
  if (superdocs) {
    try {
      const exported = await superdocs.exportDocument({
        html,
        title: releaseDocumentTitle(target),
        format,
        idempotencyKey: `release:${target.owner}/${target.repo}:${target.releaseId}:${target.tagName}`
      });

      return {
        data: exported.data,
        contentType: exported.contentType,
        extension: format,
        mode: "superdocs"
      };
    } catch {
      // Fall back to the exact same HTML source so the release document still
      // exists even when SuperDocs export is unavailable.
    }
  }

  return {
    data: new TextEncoder().encode(html),
    contentType: "text/html; charset=utf-8",
    extension: "html",
    mode: "local-html"
  };
}

async function findExistingAsset({
  client,
  target,
  assetName
}: {
  client: GitHubReleaseClient;
  target: ReleaseTarget;
  assetName: string;
}): Promise<boolean> {
  const assets = await client.listReleaseAssets({
    owner: target.owner,
    repo: target.repo,
    release_id: target.releaseId
  });

  return assets.some((asset) => asset.name === assetName);
}
