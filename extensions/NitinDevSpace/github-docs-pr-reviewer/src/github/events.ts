import { parseCommand, type ParsedCommand } from "../commands/parser.js";
import { runStaticReview } from "../review/runner.js";
import type { ChangedFile } from "../review/scanner.js";

export const supportedGitHubEvents = [
  "pull_request",
  "issue_comment",
  "release",
  "push"
] as const;

export type SupportedGitHubEvent = (typeof supportedGitHubEvents)[number];

export type GitHubWebhookEnvelope = {
  event: string;
  deliveryId: string;
  payload: unknown;
};

export type WebhookResult = {
  accepted: boolean;
  action: "queued" | "ignored";
  reason?: string;
  runKey?: string;
  review?: {
    filesScanned: number;
    docsReviewed: number;
    findingsGenerated: number;
    findingsPosted: number;
    findingsSuppressed: number;
  };
  command?: {
    verb: ParsedCommand["verb"];
    target?: string;
  };
  commandStatus?: string;
  reviewStatus?: string;
  releaseStatus?: string;
};

export type GitHubWebhookHandlers = {
  onPullRequest: (envelope: GitHubWebhookEnvelope) => Promise<WebhookResult>;
  onIssueComment: (envelope: GitHubWebhookEnvelope) => Promise<WebhookResult>;
  onRelease: (envelope: GitHubWebhookEnvelope) => Promise<WebhookResult>;
  onPush: (envelope: GitHubWebhookEnvelope) => Promise<WebhookResult>;
};

export type CommandContext = {
  installationId: number;
  owner: string;
  repo: string;
  pullNumber: number;
  requestedBy: string;
  command: ParsedCommand;
};

export type PullRequestReviewContext = {
  installationId: number;
  owner: string;
  repo: string;
  pullNumber: number;
  headSha: string;
};

/** Reviews one pull request head commit. Injectable so routing stays keyless. */
export type PullRequestReviewer = (
  context: PullRequestReviewContext
) => Promise<{ status: string }>;

/**
 * Runs a parsed command against GitHub. Left injectable so webhook routing stays
 * testable without credentials: with no executor, a command is parsed, validated
 * and queued, but nothing is written.
 */
export type CommandExecutor = (
  context: CommandContext
) => Promise<{ status: string }>;

export type ReleaseContext = {
  installationId: number;
  owner: string;
  repo: string;
  releaseId: number;
  tagName: string;
  name?: string;
  publishedAt?: string;
  body?: string;
  htmlUrl?: string;
};

/**
 * Generates and attaches the release document. Injectable for the same reason as
 * the command executor: routing stays testable with no credentials.
 */
export type ReleaseDocumentGenerator = (
  context: ReleaseContext
) => Promise<{ status: string }>;

export type WebhookDependencies = {
  executeCommand?: CommandExecutor;
  reviewPullRequest?: PullRequestReviewer;
  generateReleaseDocument?: ReleaseDocumentGenerator;
};

type MinimalRepository = {
  full_name?: string;
};

type MinimalInstallation = {
  id?: number;
};

type MinimalPullRequestPayload = {
  action?: string;
  number?: number;
  repository?: MinimalRepository;
  installation?: MinimalInstallation;
  pull_request?: {
    number?: number;
    head?: {
      sha?: string;
    };
  };
  changed_files_fixture?: ChangedFile[];
};

type MinimalIssueCommentPayload = {
  action?: string;
  repository?: MinimalRepository;
  installation?: MinimalInstallation;
  issue?: {
    number?: number;
    pull_request?: unknown;
  };
  comment?: {
    body?: string;
    user?: {
      login?: string;
      type?: string;
    };
  };
};

type MinimalReleasePayload = {
  action?: string;
  repository?: MinimalRepository;
  installation?: MinimalInstallation;
  release?: {
    id?: number;
    tag_name?: string;
    name?: string;
    body?: string;
    published_at?: string;
    html_url?: string;
    draft?: boolean;
  };
};

type MinimalPushPayload = {
  ref?: string;
  after?: string;
  repository?: MinimalRepository;
};

export function createDefaultWebhookHandlers(
  dependencies: WebhookDependencies = {}
): GitHubWebhookHandlers {
  return {
    async onPullRequest(envelope) {
      const payload = envelope.payload as MinimalPullRequestPayload;
      const action = payload.action ?? "unknown";

      if (!["opened", "synchronize", "reopened"].includes(action)) {
        return ignored(`pull_request.${action} is not part of Sprint 2`);
      }

      const pullNumber = payload.number ?? payload.pull_request?.number;
      const headSha = payload.pull_request?.head?.sha;
      const runKey = [
        payload.repository?.full_name,
        `pr-${pullNumber ?? "unknown"}`,
        headSha ?? envelope.deliveryId
      ].join(":");

      // A fixture payload runs the keyless static review, which is how the review
      // rules are exercised end to end without GitHub.
      if (payload.changed_files_fixture) {
        return {
          ...queued(runKey),
          review: runStaticReview(payload.changed_files_fixture).summary
        };
      }

      if (!dependencies.reviewPullRequest) {
        return queued(runKey);
      }

      const repository = splitRepositoryFullName(payload.repository?.full_name);
      const installationId = payload.installation?.id;

      if (
        !repository ||
        pullNumber === undefined ||
        !headSha ||
        installationId === undefined
      ) {
        return {
          ...queued(runKey),
          reviewStatus: "not-reviewed",
          reason:
            "the webhook payload was missing the installation, repository, pull request number, or head SHA"
        };
      }

      const reviewed = await dependencies.reviewPullRequest({
        installationId,
        owner: repository.owner,
        repo: repository.repo,
        pullNumber,
        headSha
      });

      return {
        ...queued(runKey),
        reviewStatus: reviewed.status
      };
    },

    async onIssueComment(envelope) {
      const payload = envelope.payload as MinimalIssueCommentPayload;
      const body = payload.comment?.body ?? "";

      if (payload.action !== "created") {
        return ignored("only new issue comments are handled");
      }

      if (!payload.issue?.pull_request) {
        return ignored("issue comment is not on a pull request");
      }

      if (payload.comment?.user?.type === "Bot") {
        return ignored("commands from bots are not executed");
      }

      const parsed = parseCommand(body);

      if (!parsed.ok) {
        return ignored(
          parsed.failure === "not-a-command"
            ? "comment is not a SuperDocs command"
            : parsed.detail
        );
      }

      const requestedBy = payload.comment?.user?.login ?? "";
      const repository = splitRepositoryFullName(payload.repository?.full_name);
      const pullNumber = payload.issue.number;

      const result: WebhookResult = {
        ...queued(
          [
            payload.repository?.full_name,
            `pr-${pullNumber ?? "unknown"}`,
            `command-${envelope.deliveryId}`
          ].join(":")
        ),
        command: describeCommand(parsed.command)
      };

      if (!dependencies.executeCommand) {
        return result;
      }

      if (!repository || pullNumber === undefined || requestedBy === "") {
        return {
          ...result,
          commandStatus: "not-executed",
          reason:
            "the webhook payload was missing the repository, pull request number, or comment author"
        };
      }

      const installationId = payload.installation?.id;

      if (installationId === undefined) {
        return {
          ...result,
          commandStatus: "not-executed",
          reason: "the webhook payload was missing the installation id"
        };
      }

      const executed = await dependencies.executeCommand({
        installationId,
        owner: repository.owner,
        repo: repository.repo,
        pullNumber,
        requestedBy,
        command: parsed.command
      });

      return {
        ...result,
        commandStatus: executed.status
      };
    },

    async onRelease(envelope) {
      const payload = envelope.payload as MinimalReleasePayload;

      if (payload.action !== "published") {
        return ignored("only published releases are handled");
      }

      if (payload.release?.draft === true) {
        return ignored("draft releases are not documented");
      }

      const result = queued(
        [
          payload.repository?.full_name,
          `release-${payload.release?.id ?? payload.release?.tag_name ?? "unknown"}`
        ].join(":")
      );

      if (!dependencies.generateReleaseDocument) {
        return result;
      }

      const repository = splitRepositoryFullName(payload.repository?.full_name);
      const releaseId = payload.release?.id;
      const tagName = payload.release?.tag_name;

      if (!repository || releaseId === undefined || !tagName) {
        return {
          ...result,
          releaseStatus: "not-generated",
          reason:
            "the webhook payload was missing the repository, release id, or tag name"
        };
      }

      const installationId = payload.installation?.id;

      if (installationId === undefined) {
        return {
          ...result,
          releaseStatus: "not-generated",
          reason: "the webhook payload was missing the installation id"
        };
      }

      const generated = await dependencies.generateReleaseDocument({
        installationId,
        owner: repository.owner,
        repo: repository.repo,
        releaseId,
        tagName,
        name: payload.release?.name,
        publishedAt: payload.release?.published_at,
        body: payload.release?.body,
        htmlUrl: payload.release?.html_url
      });

      return {
        ...result,
        releaseStatus: generated.status
      };
    },

    async onPush(envelope) {
      const payload = envelope.payload as MinimalPushPayload;

      if (!payload.ref?.startsWith("refs/tags/")) {
        return ignored("push is not a tag event");
      }

      return queued(
        [
          payload.repository?.full_name,
          payload.ref.replace("refs/tags/", "tag-"),
          payload.after ?? envelope.deliveryId
        ].join(":")
      );
    }
  };
}

export async function routeGitHubWebhook(
  envelope: GitHubWebhookEnvelope,
  handlers: GitHubWebhookHandlers
): Promise<WebhookResult> {
  switch (envelope.event) {
    case "pull_request":
      return handlers.onPullRequest(envelope);
    case "issue_comment":
      return handlers.onIssueComment(envelope);
    case "release":
      return handlers.onRelease(envelope);
    case "push":
      return handlers.onPush(envelope);
    default:
      return ignored(`unsupported event: ${envelope.event}`);
  }
}

function describeCommand(command: ParsedCommand): WebhookResult["command"] {
  if (command.verb !== "apply") {
    return { verb: command.verb };
  }

  return {
    verb: "apply",
    target:
      command.target.kind === "all-safe" ? "all-safe" : command.target.findingId
  };
}

function splitRepositoryFullName(
  fullName?: string
): { owner: string; repo: string } | undefined {
  const [owner, repo, ...rest] = fullName?.split("/") ?? [];

  if (!owner || !repo || rest.length > 0) return undefined;

  return { owner, repo };
}

function queued(runKey: string): WebhookResult {
  return {
    accepted: true,
    action: "queued",
    runKey
  };
}

function ignored(reason: string): WebhookResult {
  return {
    accepted: true,
    action: "ignored",
    reason
  };
}
