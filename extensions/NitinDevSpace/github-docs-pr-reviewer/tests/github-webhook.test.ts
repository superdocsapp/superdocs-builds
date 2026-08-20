import { describe, expect, it, vi } from "vitest";
import { buildApp } from "../src/app.js";
import { loadConfig } from "../src/config.js";
import {
  createDefaultWebhookHandlers,
  type CommandExecutor,
  type GitHubWebhookHandlers
} from "../src/github/events.js";
import { createGitHubSignature } from "../src/github/signature.js";

const secret = "test-webhook-secret";

function signedHeaders(event: string, deliveryId: string, payload: string) {
  return {
    "content-type": "application/json",
    "x-github-event": event,
    "x-github-delivery": deliveryId,
    "x-hub-signature-256": createGitHubSignature(payload, secret)
  };
}

function buildTestApp(handlers?: GitHubWebhookHandlers) {
  return buildApp({
    config: loadConfig({
      NODE_ENV: "test",
      GITHUB_WEBHOOK_SECRET: secret
    }),
    webhookHandlers: handlers
  });
}

describe("GitHub webhook route", () => {
  it("rejects requests with invalid signatures", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({ action: "opened" });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: {
        "content-type": "application/json",
        "x-github-event": "pull_request",
        "x-github-delivery": "delivery-1",
        "x-hub-signature-256": "sha256=bad"
      },
      payload
    });

    expect(response.statusCode).toBe(401);
    expect(response.json()).toEqual({
      ok: false,
      error: "invalid GitHub webhook signature"
    });
  });

  it("routes pull request events to the PR handler", async () => {
    const onPullRequest = vi.fn(async () => ({
      accepted: true,
      action: "queued" as const,
      runKey: "octo/demo:pr-7:abc123"
    }));

    const app = buildTestApp({
      onPullRequest,
      onIssueComment: vi.fn(),
      onRelease: vi.fn(),
      onPush: vi.fn()
    });

    const payload = JSON.stringify({
      action: "opened",
      number: 7,
      repository: { full_name: "octo/demo" },
      pull_request: { head: { sha: "abc123" } }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("pull_request", "delivery-2", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({
      ok: true,
      accepted: true,
      action: "queued",
      runKey: "octo/demo:pr-7:abc123"
    });
    expect(onPullRequest).toHaveBeenCalledOnce();
  });

  it("runs static review when a PR payload includes changed file fixtures", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({
      action: "opened",
      number: 8,
      repository: { full_name: "octo/demo" },
      pull_request: { head: { sha: "abc999" } },
      changed_files_fixture: [
        {
          path: "README.md",
          status: "modified",
          headContent: "# Title\n\n### Skipped\n\nRelease date: TBD"
        },
        {
          path: "src/app.ts",
          status: "modified",
          headContent: "export {};"
        }
      ]
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("pull_request", "delivery-static", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({
      ok: true,
      accepted: true,
      action: "queued",
      runKey: "octo/demo:pr-8:abc999",
      review: {
        filesScanned: 2,
        docsReviewed: 1,
        findingsGenerated: 2,
        findingsPosted: 2,
        findingsSuppressed: 0
      }
    });
  });

  it("reviews a live pull request through the injected reviewer", async () => {
    const reviewPullRequest = vi.fn(async () => ({ status: "completed" }));
    const app = buildTestApp(
      createDefaultWebhookHandlers({ reviewPullRequest })
    );
    const payload = JSON.stringify({
      action: "opened",
      number: 8,
      repository: { full_name: "octo/demo" },
      installation: { id: 17 },
      pull_request: { head: { sha: "abc999" } }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("pull_request", "delivery-review", payload),
      payload
    });

    expect(response.json()).toMatchObject({
      action: "queued",
      reviewStatus: "completed"
    });
    expect(reviewPullRequest).toHaveBeenCalledWith({
      installationId: 17,
      owner: "octo",
      repo: "demo",
      pullNumber: 8,
      headSha: "abc999"
    });
  });

  it("ignores issue comments that are not SuperDocs commands", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({
      action: "created",
      repository: { full_name: "octo/demo" },
      issue: { number: 7, pull_request: {} },
      comment: { body: "Looks good" }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("issue_comment", "delivery-3", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({
      ok: true,
      accepted: true,
      action: "ignored",
      reason: "comment is not a SuperDocs command"
    });
  });

  it("runs a valid apply command through the injected executor", async () => {
    const executeCommand = vi.fn<CommandExecutor>(async () => ({
      status: "applied"
    }));
    const app = buildTestApp(createDefaultWebhookHandlers({ executeCommand }));
    const payload = JSON.stringify({
      action: "created",
      repository: { full_name: "octo/demo" },
      installation: { id: 17 },
      issue: { number: 7, pull_request: {} },
      comment: {
        body: "/superdocs apply a1b2c3d4e5",
        user: { login: "maintainer", type: "User" }
      }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("issue_comment", "delivery-cmd-1", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toMatchObject({
      action: "queued",
      command: { verb: "apply", target: "a1b2c3d4e5" },
      commandStatus: "applied"
    });
    expect(executeCommand).toHaveBeenCalledWith({
      installationId: 17,
      owner: "octo",
      repo: "demo",
      pullNumber: 7,
      requestedBy: "maintainer",
      command: {
        verb: "apply",
        target: { kind: "finding", findingId: "a1b2c3d4e5" }
      }
    });
  });

  it("does not execute a command that is only quoted in a comment", async () => {
    const executeCommand = vi.fn<CommandExecutor>(async () => ({
      status: "applied"
    }));
    const app = buildTestApp(createDefaultWebhookHandlers({ executeCommand }));
    const payload = JSON.stringify({
      action: "created",
      repository: { full_name: "octo/demo" },
      issue: { number: 7, pull_request: {} },
      comment: {
        body: "The docs say:\n\n```\n/superdocs apply a1b2c3d4e5\n```",
        user: { login: "maintainer", type: "User" }
      }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("issue_comment", "delivery-cmd-2", payload),
      payload
    });

    expect(response.json()).toMatchObject({ action: "ignored" });
    expect(executeCommand).not.toHaveBeenCalled();
  });

  it("does not execute commands posted by bots", async () => {
    const executeCommand = vi.fn<CommandExecutor>(async () => ({
      status: "applied"
    }));
    const app = buildTestApp(createDefaultWebhookHandlers({ executeCommand }));
    const payload = JSON.stringify({
      action: "created",
      repository: { full_name: "octo/demo" },
      issue: { number: 7, pull_request: {} },
      comment: {
        body: "/superdocs apply a1b2c3d4e5",
        user: { login: "some-bot", type: "Bot" }
      }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("issue_comment", "delivery-cmd-3", payload),
      payload
    });

    expect(response.json()).toMatchObject({
      action: "ignored",
      reason: "commands from bots are not executed"
    });
    expect(executeCommand).not.toHaveBeenCalled();
  });

  it("names the cause when a command is malformed", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({
      action: "created",
      repository: { full_name: "octo/demo" },
      issue: { number: 7, pull_request: {} },
      comment: {
        body: "/superdocs apply",
        user: { login: "maintainer", type: "User" }
      }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("issue_comment", "delivery-cmd-4", payload),
      payload
    });

    const body = response.json();
    expect(body.action).toBe("ignored");
    expect(body.reason).toContain("Name what to apply");
  });

  it("queues published releases", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({
      action: "published",
      repository: { full_name: "octo/demo" },
      release: { id: 99, tag_name: "v1.0.0" }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("release", "delivery-4", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({
      ok: true,
      accepted: true,
      action: "queued",
      runKey: "octo/demo:release-99"
    });
  });

  it("generates a release document for a published release", async () => {
    const generateReleaseDocument = vi.fn(async () => ({ status: "attached" }));
    const app = buildTestApp(
      createDefaultWebhookHandlers({ generateReleaseDocument })
    );
    const payload = JSON.stringify({
      action: "published",
      repository: { full_name: "octo/demo" },
      installation: { id: 17 },
      release: {
        id: 99,
        tag_name: "v1.0.0",
        name: "First release",
        body: "## Notes",
        published_at: "2026-08-18T10:00:00Z",
        html_url: "https://github.com/octo/demo/releases/tag/v1.0.0"
      }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("release", "delivery-rel-1", payload),
      payload
    });

    expect(response.json()).toMatchObject({
      action: "queued",
      releaseStatus: "attached"
    });
    expect(generateReleaseDocument).toHaveBeenCalledWith({
      installationId: 17,
      owner: "octo",
      repo: "demo",
      releaseId: 99,
      tagName: "v1.0.0",
      name: "First release",
      body: "## Notes",
      publishedAt: "2026-08-18T10:00:00Z",
      htmlUrl: "https://github.com/octo/demo/releases/tag/v1.0.0"
    });
  });

  it("does not document a draft release", async () => {
    const generateReleaseDocument = vi.fn(async () => ({ status: "attached" }));
    const app = buildTestApp(
      createDefaultWebhookHandlers({ generateReleaseDocument })
    );
    const payload = JSON.stringify({
      action: "published",
      repository: { full_name: "octo/demo" },
      release: { id: 99, tag_name: "v1.0.0", draft: true }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("release", "delivery-rel-2", payload),
      payload
    });

    expect(response.json()).toMatchObject({
      action: "ignored",
      reason: "draft releases are not documented"
    });
    expect(generateReleaseDocument).not.toHaveBeenCalled();
  });

  it("queues tag pushes", async () => {
    const app = buildTestApp();
    const payload = JSON.stringify({
      ref: "refs/tags/v1.0.0",
      after: "def456",
      repository: { full_name: "octo/demo" }
    });

    const response = await app.inject({
      method: "POST",
      url: "/webhooks/github",
      headers: signedHeaders("push", "delivery-5", payload),
      payload
    });

    expect(response.statusCode).toBe(202);
    expect(response.json()).toEqual({
      ok: true,
      accepted: true,
      action: "queued",
      runKey: "octo/demo:tag-v1.0.0:def456"
    });
  });
});
