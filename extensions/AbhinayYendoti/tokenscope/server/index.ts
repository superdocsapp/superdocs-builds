import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import express from "express";
import { loadConfig } from "./config.js";
import { createRouter } from "./routes.js";

/**
 * TokenScope server.
 *
 * It exists for one reason: the SuperDocs API key must not be in the browser
 * bundle, and a Word task pane is a browser. Everything else here is a static
 * file server.
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(here, "..", "dist");

const config = loadConfig();
const app = express();

app.use(express.json({ limit: "24mb" }));
app.use("/api", createRouter());

if (existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/.*/u, (_req, res) => res.sendFile(path.join(dist, "index.html")));
}

app.listen(config.port, "127.0.0.1", () => {
  console.log(`TokenScope on http://127.0.0.1:${config.port}`);
  console.log(`  SuperDocs   ${config.baseUrl}  (model tier: ${config.modelTier})`);
  console.log(
    config.configured
      ? "  API key     present"
      : "  API key     MISSING - set SUPERDOCS_API_KEY in .env.local"
  );

  if (!existsSync(dist)) {
    console.log("  UI          not built; run `npm run dev` for the Vite dev server");
  }
});
