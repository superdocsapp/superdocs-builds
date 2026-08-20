import type { PullRequestTarget, PreviewArtifact } from "../github/review-format.js";
import type { ReviewableDoc } from "../review/scanner.js";
import type { SuperDocsClient, SuperDocsExportFormat } from "../superdocs/client.js";
import { storePreviewArtifact, type StoredPreviewArtifact } from "./artifacts.js";
import { docsToHtml } from "./markdown-html.js";

export type PreviewGenerationResult = {
  artifact: StoredPreviewArtifact;
  mode: "superdocs" | "local-html";
  sourceHtml: string;
};

export async function generatePreview({
  target,
  docs,
  artifactsDir,
  client,
  format = "docx",
  publicBaseUrl
}: {
  target: PullRequestTarget;
  docs: ReviewableDoc[];
  artifactsDir: string;
  client?: SuperDocsClient;
  format?: SuperDocsExportFormat;
  publicBaseUrl?: string;
}): Promise<PreviewGenerationResult> {
  const sourceHtml = docsToHtml(docs, `${target.owner}/${target.repo} documentation preview`);

  if (client) {
    const exported = await client.exportDocument({
      html: sourceHtml,
      title: `${target.owner}/${target.repo} PR #${target.pullNumber}`,
      format,
      idempotencyKey: `preview:${target.owner}/${target.repo}:${target.pullNumber}:${target.headSha}`
    });
    return {
      artifact: await storePreviewArtifact({
        artifactsDir,
        target,
        filename: exported.filename,
        data: exported.data,
        contentType: exported.contentType,
        publicBaseUrl
      }),
      mode: "superdocs",
      sourceHtml
    };
  }

  return {
    artifact: await storePreviewArtifact({
      artifactsDir,
      target,
      filename: "preview.html",
      data: new TextEncoder().encode(sourceHtml),
      contentType: "text/html; charset=utf-8",
      publicBaseUrl
    }),
    mode: "local-html",
    sourceHtml
  };
}

export function previewLink(artifact: StoredPreviewArtifact): PreviewArtifact {
  return { url: artifact.url, label: artifact.label };
}
