import type { FastifyInstance } from "fastify";
import type { AppConfig } from "../config.js";
import {
  createDefaultWebhookHandlers,
  type GitHubWebhookHandlers,
  routeGitHubWebhook
} from "./events.js";
import { verifyGitHubSignature } from "./signature.js";

export type RegisterGitHubWebhookOptions = {
  app: FastifyInstance;
  config: AppConfig;
  handlers?: GitHubWebhookHandlers;
};

export function registerGitHubWebhookRoute({
  app,
  config,
  handlers = createDefaultWebhookHandlers()
}: RegisterGitHubWebhookOptions) {
  app.addContentTypeParser(
    "application/json",
    { parseAs: "string" },
    (_request, body, done) => {
      done(null, body);
    }
  );

  app.post("/webhooks/github", async (request, reply) => {
    const rawBody = typeof request.body === "string" ? request.body : "";
    const signature = request.headers["x-hub-signature-256"];
    const event = request.headers["x-github-event"];
    const deliveryId = request.headers["x-github-delivery"];

    if (typeof event !== "string" || typeof deliveryId !== "string") {
      return reply.code(400).send({
        ok: false,
        error: "missing required GitHub webhook headers"
      });
    }

    if (
      !verifyGitHubSignature({
        payload: rawBody,
        signature: Array.isArray(signature) ? signature[0] : signature,
        secret: config.GITHUB_WEBHOOK_SECRET
      })
    ) {
      return reply.code(401).send({
        ok: false,
        error: "invalid GitHub webhook signature"
      });
    }

    let payload: unknown;
    try {
      payload = JSON.parse(rawBody);
    } catch {
      return reply.code(400).send({
        ok: false,
        error: "invalid JSON payload"
      });
    }

    const result = await routeGitHubWebhook(
      {
        event,
        deliveryId,
        payload
      },
      handlers
    );

    return reply.code(202).send({
      ok: true,
      ...result
    });
  });
}

