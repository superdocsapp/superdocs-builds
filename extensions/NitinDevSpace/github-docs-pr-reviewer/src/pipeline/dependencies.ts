import { runApplyCommand, type ApplyTarget } from "../commands/apply-runner.js";
import type { AppConfig } from "../config.js";
import {
  createInstallationClientFactory,
  readAppCredentials,
  type InstallationClientFactory
} from "../github/app-auth.js";
import type { WebhookDependencies } from "../github/events.js";
import { createOctokitApplyClient } from "../github/octokit-apply-client.js";
import { createOctokitReleaseClient } from "../github/octokit-release-client.js";
import { createOctokitReviewClient } from "../github/octokit-review-client.js";
import { generateReleaseDocument } from "../release/release-document.js";
import { HttpSuperDocsClient, type SuperDocsClient } from "../superdocs/client.js";
import { runReviewPipeline, type DocsReviewClient } from "./review-pipeline.js";

export type BuiltDependencies = {
  dependencies: WebhookDependencies;
  /** Why the live GitHub path is inactive, when it is. */
  inactiveReason?: string;
};

/**
 * Wires the live GitHub path when credentials are present.
 *
 * Without credentials the app still starts, still verifies signatures, and still
 * parses and validates events; it simply does not call GitHub. That keeps a fresh
 * clone runnable and makes the missing piece obvious instead of fatal.
 */
export function buildWebhookDependencies(
  config: AppConfig,
  log: (message: string) => void = () => {}
): BuiltDependencies {
  const credentials = readAppCredentials(config);

  if (!credentials.ok) {
    log(
      `GitHub App credentials are not configured (${credentials.reason}). Webhooks will be verified and parsed, but nothing will be posted to GitHub. Run "npm run demo" to see the full flow offline.`
    );
    return { dependencies: {}, inactiveReason: credentials.reason };
  }

  const clientFor = createInstallationClientFactory(credentials.credentials);
  const superdocs = buildSuperDocsClient(config, log);

  return {
    dependencies: {
      async executeCommand(context) {
        const client = await docsClientFor(clientFor, context.installationId);

        if (context.command.verb !== "apply") {
          return { status: `${context.command.verb}-not-implemented` };
        }

        const target: ApplyTarget =
          context.command.target.kind === "all-safe"
            ? { kind: "all-safe" }
            : {
                kind: "finding",
                findingId: context.command.target.findingId
              };

        const result = await runApplyCommand({
          client,
          owner: context.owner,
          repo: context.repo,
          pullNumber: context.pullNumber,
          requestedBy: context.requestedBy,
          target
        });

        return { status: result.status };
      },

      async reviewPullRequest(context) {
        const client = await docsClientFor(clientFor, context.installationId);

        const result = await runReviewPipeline({
          client,
          target: {
            owner: context.owner,
            repo: context.repo,
            pullNumber: context.pullNumber,
            headSha: context.headSha
          },
          artifactsDir: config.ARTIFACTS_DIR,
          superdocs,
          publicArtifactBaseUrl: config.PUBLIC_ARTIFACT_BASE_URL
        });

        return { status: result.status };
      },

      async generateReleaseDocument(context) {
        const octokit = await clientFor(context.installationId);

        const result = await generateReleaseDocument({
          client: createOctokitReleaseClient(octokit as never),
          target: {
            owner: context.owner,
            repo: context.repo,
            releaseId: context.releaseId,
            tagName: context.tagName,
            name: context.name,
            publishedAt: context.publishedAt,
            body: context.body,
            htmlUrl: context.htmlUrl
          },
          artifactsDir: config.ARTIFACTS_DIR,
          superdocs,
          publicBaseUrl: config.PUBLIC_ARTIFACT_BASE_URL
        });

        return { status: result.status };
      }
    }
  };
}

async function docsClientFor(
  clientFor: InstallationClientFactory,
  installationId: number
): Promise<DocsReviewClient> {
  const octokit = await clientFor(installationId);
  const comments = createOctokitReviewClient(octokit as never);

  return {
    ...comments,
    ...createOctokitApplyClient(octokit as never, comments)
  };
}

export function buildSuperDocsClient(
  config: AppConfig,
  log: (message: string) => void
): SuperDocsClient | undefined {
  if (config.SUPERDOCS_API_KEY === "") {
    log(
      "SUPERDOCS_API_KEY is not set. Previews and release documents will be generated as local HTML from the same source markup an export would use."
    );
    return undefined;
  }

  return new HttpSuperDocsClient({
    apiKey: config.SUPERDOCS_API_KEY,
    baseUrl: config.SUPERDOCS_API_BASE_URL
  });
}
