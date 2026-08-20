import Fastify from "fastify";
import type { AppConfig } from "./config.js";
import {
  registerGitHubWebhookRoute,
  type RegisterGitHubWebhookOptions
} from "./github/webhook-route.js";

type BuildAppOptions = {
  config: AppConfig;
  webhookHandlers?: RegisterGitHubWebhookOptions["handlers"];
};

export function buildApp({ config, webhookHandlers }: BuildAppOptions) {
  const app = Fastify({
    logger:
      config.NODE_ENV === "test"
        ? false
        : {
            level: config.LOG_LEVEL
          }
  });

  app.get("/health", async () => {
    return {
      ok: true,
      service: "docs-pr-reviewer",
      env: config.NODE_ENV
    };
  });

  registerGitHubWebhookRoute({
    app,
    config,
    handlers: webhookHandlers
  });

  return app;
}
