import express from "express";
import { resolve } from "node:path";

const app = express();
const dev = process.argv.includes("--dev");
const port = Number(process.env.PORT ?? 5173);
const baseUrl = "https://api.superdocs.app";
const reviewMessage = "Review this localization kit for translator-readiness. Improve only unclear context notes or inconsistent style instructions. Preserve every string ID, source string, character limit, speaker, scene note, protected token and do-not-translate entry exactly. Propose changes for human approval; do not auto-apply.";

app.use(express.json({ limit: "2mb" }));

function apiKey() {
  const key = process.env.SUPERDOCS_API_KEY;
  if (!key) throw new Error("SUPERDOCS_API_KEY is missing on the server.");
  return key;
}

async function callSuperDocs(path, options = {}) {
  return fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${apiKey()}`, ...options.headers },
  });
}

async function sendError(response, res) {
  const detail = await response.text();
  res.status(response.status).type(response.headers.get("content-type") ?? "text/plain").send(detail);
}

app.post("/api/superdocs/reviews", async (req, res) => {
  const { sessionId, html } = req.body ?? {};
  if (typeof sessionId !== "string" || !sessionId || typeof html !== "string" || !html.trim()) return res.status(422).json({ detail: "sessionId and non-empty html are required." });
  try {
    const response = await callSuperDocs("/v1/chat/async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, document_html: html, approval_mode: "ask_every_time", message: reviewMessage }),
    });
    if (!response.ok) return sendError(response, res);
    res.json(await response.json());
  } catch (error) {
    res.status(500).json({ detail: error instanceof Error ? error.message : "Could not reach SuperDocs." });
  }
});

app.get("/api/superdocs/jobs/:jobId", async (req, res) => {
  try {
    const response = await callSuperDocs(`/v1/jobs/${encodeURIComponent(req.params.jobId)}`);
    if (!response.ok) return sendError(response, res);
    res.json(await response.json());
  } catch (error) {
    res.status(500).json({ detail: error instanceof Error ? error.message : "Could not poll SuperDocs." });
  }
});

app.post("/api/superdocs/approvals", async (req, res) => {
  const { sessionId, jobId, changes } = req.body ?? {};
  if (typeof sessionId !== "string" || typeof jobId !== "string" || !Array.isArray(changes)) return res.status(422).json({ detail: "sessionId, jobId and changes are required." });
  try {
    const response = await callSuperDocs(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, approved: true, changes }),
    });
    if (!response.ok) return sendError(response, res);
    res.json(await response.json());
  } catch (error) {
    res.status(500).json({ detail: error instanceof Error ? error.message : "Could not submit decisions." });
  }
});

app.post("/api/superdocs/exports", async (req, res) => {
  const { sessionId } = req.body ?? {};
  if (typeof sessionId !== "string" || !sessionId) return res.status(422).json({ detail: "sessionId is required." });
  try {
    const response = await callSuperDocs("/v1/documents/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, format: "docx", filename: "localization-kit.docx" }),
    });
    if (!response.ok) return sendError(response, res);
    res.status(200);
    res.set("Content-Type", response.headers.get("content-type") ?? "application/octet-stream");
    res.set("Content-Disposition", "attachment; filename=localization-kit.docx");
    const warnings = response.headers.get("x-export-warnings");
    if (warnings) res.set("X-Export-Warnings", warnings);
    res.send(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    res.status(500).json({ detail: error instanceof Error ? error.message : "Could not export the kit." });
  }
});

if (dev) {
  const { createServer: createViteServer } = await import("vite");
  const vite = await createViteServer({ server: { middlewareMode: true }, appType: "spa" });
  app.use(vite.middlewares);
} else {
  app.use(express.static(resolve("dist")));
  app.use((_req, res) => res.sendFile(resolve("dist", "index.html")));
}

app.listen(port, () => console.log(`Kitline listening on http://localhost:${port}`));
