import { buildApp } from "./app.js";
import { loadConfig } from "./config.js";
import { createDefaultWebhookHandlers } from "./github/events.js";
import { buildWebhookDependencies } from "./pipeline/dependencies.js";

const config = loadConfig();
const { dependencies, inactiveReason } = buildWebhookDependencies(config);
const app = buildApp({
  config,
  webhookHandlers: createDefaultWebhookHandlers(dependencies)
});

if (inactiveReason) {
  app.log.warn(
    { reason: inactiveReason },
    "GitHub App credentials are not configured. Webhooks will be verified and parsed, but nothing will be posted to GitHub. Run npm run demo to see the full flow offline."
  );
}

try {
  await app.listen({
    port: config.PORT,
    host: "0.0.0.0"
  });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
