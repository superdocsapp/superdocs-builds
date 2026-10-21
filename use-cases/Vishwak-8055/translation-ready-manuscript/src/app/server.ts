import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { loadLocalEnv } from "../config/env.js";
import { parseDocumentInput } from "../ingest/documentInput.js";
import { parseManuscript } from "../ingest/parseManuscript.js";
import { HeuristicLlmProvider } from "../extract/heuristicProvider.js";
import { AnthropicProvider } from "../extract/llmProvider.js";
import { prepareRun, getRun, reviewTerms, validateReturnedTranslation, exportArtifacts, setFindingReviewStatus, updateSuperDocsState } from "../workflow/workflow.js";
import { SuperDocsIntegration } from "../superdocs/integration.js";
import type { ApproveDecision } from "../superdocs/client.js";
import { diffDocumentBodies } from "../diff/documentDiff.js";

loadLocalEnv();

const port = Number(process.env.PORT ?? 8787);
const MAX_BODY_BYTES = 64 * 1024 * 1024;
const provider = process.env.ANTHROPIC_API_KEY ? new AnthropicProvider() : new HeuristicLlmProvider();
const superdocs = new SuperDocsIntegration();

const staticJs = readFileSync(join(process.cwd(), "app.js"), "utf8");
const staticHtml = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Translation-ready Manuscript</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#171717;background:#f5f5f2}
*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:0 auto;padding:34px 22px 70px}.hero{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:24px}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;color:#737373;font-weight:700}.hero h1{font-size:34px;line-height:1.05;margin:8px 0}.hero p{color:#666;margin:0;max-width:720px}.grid{display:grid;gap:16px}.card{background:#fff;border:1px solid #dddcd6;border-radius:16px;padding:20px;box-shadow:0 8px 28px rgba(0,0,0,.04)}.step{display:flex;justify-content:space-between;align-items:center;gap:16px}.step h2{font-size:18px;margin:0 0 4px}.step p{margin:0;color:#777;font-size:13px}.badge{display:inline-flex;align-items:center;padding:5px 9px;border-radius:999px;background:#eee;color:#555;font-size:12px;font-weight:700}.badge.ok{background:#e8f6ed;color:#17663a}.badge.warn{background:#fff5d8;color:#805b00}.badge.bad{background:#fde8e8;color:#9c2424}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:14px}input[type=file],input[type=text],textarea,select{width:100%;border:1px solid #cfcfc8;border-radius:9px;padding:10px;background:#fff}button{border:1px solid #171717;background:#171717;color:#fff;border-radius:9px;padding:9px 13px;font-weight:650;cursor:pointer}button.secondary{background:#fff;color:#171717}button.danger{background:#fff;color:#a32626;border-color:#d7a0a0}button:disabled{opacity:.45;cursor:not-allowed}.status{margin-top:12px;padding:11px 12px;border-radius:9px;background:#f4f4f1;color:#555;font-size:13px;white-space:pre-wrap}.profile{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:14px}.metric{padding:11px;border:1px solid #e5e4de;border-radius:10px;background:#fafaf8}.metric b{display:block;font-size:17px}.metric span{font-size:11px;color:#777}.terms{margin-top:14px;border:1px solid #e5e4de;border-radius:10px;overflow:hidden}.term{display:grid;grid-template-columns:1fr auto;gap:12px;padding:13px;border-bottom:1px solid #eee}.term:last-child{border-bottom:0}.term-name{font-weight:750}.term-meta{font-size:12px;color:#737373;margin-top:4px}.signal{display:inline-block;margin:5px 5px 0 0;padding:3px 6px;border-radius:999px;background:#f0f0ec;color:#62625d;font-size:10px}.actions{display:flex;gap:6px;align-items:center}.packet-grid,.qa-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}.panel{border:1px solid #e5e4de;border-radius:10px;padding:13px;background:#fafaf8}.panel h3{margin:0 0 8px;font-size:13px}.panel pre{margin:0;max-height:260px;overflow:auto;white-space:pre-wrap;font-size:12px}.qa-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.chapter{padding:11px;border:1px solid #e5e4de;border-radius:10px}.chapter b{display:block}.finding{border-top:1px solid #e5e4de;padding:14px 0}.finding:first-child{border-top:0}.finding-title{display:flex;justify-content:space-between;gap:10px}.severity{font-size:11px;font-weight:800;padding:4px 7px;border-radius:999px}.high{background:#fde8e8;color:#9c2424}.medium{background:#fff4d5;color:#7a5700}.low{background:#e8f1ff;color:#2b5e99}.evidence{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}.evidence pre{background:#fff;border:1px solid #e5e4de;padding:10px;border-radius:8px;white-space:pre-wrap;font-size:12px}.superdocs-status{display:flex;justify-content:space-between;gap:12px;align-items:center}.change{border:1px solid #e5e4de;border-radius:10px;padding:12px;margin-top:9px;background:#fafaf8}.change pre{white-space:pre-wrap;background:#fff;border:1px solid #eee;padding:9px;border-radius:7px}.small{font-size:12px;color:#777}.hidden{display:none}@media(max-width:800px){.profile,.qa-summary,.packet-grid,.qa-grid,.evidence{grid-template-columns:1fr 1fr}.hero{display:block}}@media(max-width:560px){.profile,.qa-summary,.packet-grid,.qa-grid,.evidence{grid-template-columns:1fr}.term{grid-template-columns:1fr}.actions{justify-content:flex-start}}
</style></head>
<body><main>
<header class="hero"><div><div class="eyebrow">SuperDocs use case</div><h1>Translation-ready Manuscript</h1><p>Prepare a manuscript with evidence-backed terminology and formatting guidance, review the handoff, optionally send it through SuperDocs, then validate the returned translation chapter by chapter.</p></div><span id="health" class="badge">Local service</span></header>
<div class="grid">
<section class="card"><div class="step"><div><h2>01 · Manuscript intake</h2><p>Accept a declared manuscript format and preserve the original content hash.</p></div><span id="prepareBadge" class="badge">Waiting</span></div><div class="row"><input id="file" type="file" accept=".txt,.text,.md,.markdown,.docx,.pdf,.html,.htm"></div><div class="row"><button id="aliceDemoBtn" class="secondary" type="button">Use included Alice demo</button><button id="secondDemoBtn" class="secondary" type="button">Use second-manuscript demo</button></div><div class="row"><input id="lang" type="text" value="Spanish" placeholder="Target language"><button id="prepareBtn" type="button">Analyze manuscript</button></div><div id="status" class="status">Choose a manuscript to begin.</div><div id="profile" class="profile hidden"></div></section>
<section class="card"><div class="step"><div><h2>02 · Evidence-backed term review</h2><p>AI suggestions are filtered against the actual manuscript. Nothing becomes enforceable until a human approves it.</p></div><span id="termBadge" class="badge">No run</span></div><div class="row"><button class="secondary" id="approveAllBtn" type="button" disabled>Approve all</button><button class="secondary" id="rejectAllBtn" type="button" disabled>Reject all</button></div><div id="terms" class="terms"><div class="status">No manuscript analyzed yet.</div></div></section>
<section class="card"><div class="step"><div><h2>03 · Translation packet</h2><p>Clean source, term base, pronunciation/meaning notes, DNT rules, style, formatting semantics and instructions.</p></div><span id="packetBadge" class="badge">Waiting for review</span></div><div class="packet-grid"><div class="panel"><h3>Packet summary</h3><pre id="packetSummary">—</pre></div><div class="panel"><h3>Source metadata</h3><pre id="sourceMetadata">—</pre></div></div><div class="row"><button class="secondary" id="exportBtn" type="button" disabled>Export packet artifacts</button></div></section>
<section class="card"><div class="step"><div><h2>04 · Returned translation QA</h2><p>Upload the returned translation in the same supported format. Chapter structure and protected terminology are checked conservatively.</p></div><span id="qaBadge" class="badge">Waiting</span></div><div class="row"><input id="translation" type="file" accept=".txt,.text,.md,.markdown,.docx,.pdf,.html,.htm"></div><div class="row"><button id="qaBtn" type="button" disabled>Run chapter QA</button></div><div id="qaSummary" class="qa-summary" style="margin-top:14px"></div><div id="chapters" class="grid" style="margin-top:12px"></div><div id="findings" class="grid" style="margin-top:12px"></div></section>
<section class="card"><div class="step"><div><h2>05 · Live SuperDocs integration</h2><p>Server-side API key only. Send the prepared HTML, request a targeted edit, review proposed changes, approve/reject, and export DOCX.</p></div><span id="sdBadge" class="badge">Not checked</span></div><div class="row"><button class="secondary" id="sdCheckBtn" type="button">Check API connection</button><button id="sdSendBtn" type="button" disabled>Send packet to SuperDocs</button><button class="secondary" id="sdRefreshBtn" type="button" disabled>Refresh job</button><button class="secondary" id="sdExportBtn" type="button" disabled>Export DOCX</button></div><div class="row"><label class="small">Precision tier <select id="sdTier"><option value="core">Core</option><option value="turbo">Turbo</option><option value="pro" selected>Pro</option><option value="max">Max</option></select></label><label class="small">Thinking depth <select id="sdDepth"><option value="fast">Fast</option><option value="balanced" selected>Balanced</option><option value="deep">Deep</option></select></label></div><textarea id="instruction" rows="4" style="margin-top:12px" placeholder="Targeted instruction to SuperDocs">Prepare this manuscript for translation while preserving approved protected terminology, documented formatting-carried meaning, chapter structure, and the translator-facing guidance. Do not invent or rewrite content outside the requested scope.</textarea><div id="sdStatus" class="status">No live SuperDocs operation has been started.</div><div id="changes"></div></section>
</div></main>
<script src="/app.js" defer></script></body></html>`;

function json(res: ServerResponse, status: number, value: unknown): void {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(value));
}

function body(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let total = 0;
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => {
      total += chunk.byteLength;
      if (total > MAX_BODY_BYTES) {
        reject(new Error(`Request exceeds ${MAX_BODY_BYTES / 1024 / 1024} MB.`));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}")); }
      catch (error) { reject(new Error(`Invalid JSON request: ${error instanceof Error ? error.message : String(error)}`)); }
    });
    req.on("error", reject);
  });
}

async function rawBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    let total = 0;
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => {
      total += chunk.byteLength;
      if (total > MAX_BODY_BYTES) {
        reject(new Error(`Request exceeds ${MAX_BODY_BYTES / 1024 / 1024} MB.`));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function headerFilename(req: IncomingMessage, fallback = "manuscript.txt"): string {
  const value = req.headers["x-filename"];
  return typeof value === "string" && value.trim() ? decodeURIComponent(value) : fallback;
}

function asBytes(value: unknown): Uint8Array {
  if (!Array.isArray(value) || value.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) throw new Error("File payload must be a byte array.");
  return Uint8Array.from(value as number[]);
}

function packetIntegrity(sourceHtml: string, returnedHtml: string): { preservedChunkIds: number; totalSourceChunkIds: number; pass: boolean; changedChunks: number } {
  const extractIds = (html: string): Set<string> => new Set([...html.matchAll(/data-chunk-id=["']([^"']+)["']/g)].map((match) => match[1]!));
  const sourceIds = extractIds(sourceHtml);
  const returnedIds = extractIds(returnedHtml);
  const preserved = [...sourceIds].filter((id) => returnedIds.has(id)).length;
  const diff = diffDocumentBodies(sourceHtml, returnedHtml);
  return { preservedChunkIds: preserved, totalSourceChunkIds: sourceIds.size, pass: preserved === sourceIds.size, changedChunks: diff.changes.length };
}

const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
  try {
    const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
    if (req.method === "GET" && url.pathname === "/health") return json(res, 200, { status: "ok", service: "translation-ready-manuscript" });
    if (req.method === "GET" && url.pathname === "/") { res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store, no-cache, must-revalidate" }); return res.end(staticHtml); }
     if (req.method === "GET" && url.pathname === "/app.js") { res.writeHead(200, { "content-type": "application/javascript; charset=utf-8", "cache-control": "no-store, no-cache, must-revalidate" }); return res.end(staticJs); }
     if (req.method === "GET" && url.pathname === "/favicon.ico") { res.writeHead(204); return res.end(); }

    if (req.method === "GET" && (url.pathname === "/api/demo/alice" || url.pathname === "/api/demo/second")) {
      const demoPath = url.pathname.endsWith("/alice")
        ? join(process.cwd(), "tests", "fixtures", "alice.txt")
        : join(process.cwd(), "examples", "second-manuscript", "source.txt");
      if (!existsSync(demoPath)) return json(res, 404, { error: "Demo manuscript not found." });
      const demoBytes = readFileSync(demoPath);
      return json(res, 200, { filename: demoPath.endsWith("alice.txt") ? "alice.txt" : "second-manuscript.txt", contentType: "text/plain", base64: demoBytes.toString("base64") });
    }

    if (req.method === "POST" && url.pathname === "/api/prepare") {
      const contentType = String(req.headers["content-type"] ?? "").toLowerCase();
      let filename = headerFilename(req);
      let targetLanguage = decodeURIComponent(String(req.headers["x-target-language"] ?? "Unspecified"));
      let sourceBytes: Uint8Array;
      if (contentType.includes("application/json")) {
        const b = await body(req) as Record<string, unknown>;
        sourceBytes = asBytes(b.bytes);
        filename = String(b.filename ?? filename);
        targetLanguage = String(b.targetLanguage ?? targetLanguage);
      } else {
        sourceBytes = new Uint8Array(await rawBody(req));
      }
      const input = parseDocumentInput(filename, sourceBytes);
      const manuscript = parseManuscript(input.rawText, { sourceFilename: input.filename, sourceFormat: input.format });
      const run = await prepareRun(manuscript, provider, targetLanguage, false);
      const runDir = join(process.cwd(), "run-artifacts", run.id);
      mkdirSync(runDir, { recursive: true });
      writeFileSync(join(runDir, `source-original.${input.format}`), Buffer.from(sourceBytes));
      writeFileSync(join(runDir, "source-normalized.txt"), input.rawText, "utf8");
      return json(res, 200, {
        runId: run.id,
        terms: run.terms,
        memorySuggestions: run.terms.filter(t => t.memorySource === "previously_approved").length,
        extractionWarnings: run.extractionWarnings,
        profile: { format: input.format, chapters: manuscript.chapters.length, blocks: manuscript.chapters.reduce((n, c) => n + c.blocks.length, 0), sourceLanguage: manuscript.metadata.sourceLanguage, sourceBytes: input.sourceBytes },
        packetSummary: { title: run.packet?.manuscriptTitle, termCount: run.packet?.termBase.length, dntCount: run.packet?.doNotTranslateRules.length, formattingRules: run.packet?.formattingGuidance.length, styleStatus: run.packet?.styleNote.status },
        sourceMetadata: run.packet?.sourceMetadata,
        metrics: run.metrics,
      });
    }

    if (req.method === "POST" && url.pathname.startsWith("/api/review/")) {
      const id = url.pathname.split("/").pop()!;
      const b = await body(req) as Record<string, unknown>;
      const current = getRun(id);
      if (!current) return json(res, 404, { error: "Run not found" });
      let decisions: Array<{ termId: string; action: "approve" | "reject" }> = Array.isArray(b.decisions) ? b.decisions as Array<{ termId: string; action: "approve" | "reject" }> : [];
      if (b.approveAll === true) decisions = current.terms.filter(t => t.status === "suggested").map(t => ({ termId: t.id, action: "approve" as const }));
      if (b.rejectAll === true) decisions = current.terms.filter(t => t.status === "suggested").map(t => ({ termId: t.id, action: "reject" as const }));
      const run = reviewTerms(id, decisions);
      return json(res, 200, { runId: id, terms: run.terms, packetSummary: { termCount: run.packet?.termBase.length, dntCount: run.packet?.doNotTranslateRules.length, formattingRules: run.packet?.formattingGuidance.length }, sourceMetadata: run.packet?.sourceMetadata, metrics: run.metrics });
    }

    if (req.method === "POST" && url.pathname.startsWith("/api/qa/") && !url.pathname.endsWith("/review")) {
      const id = url.pathname.split("/").pop()!;
      const contentType = String(req.headers["content-type"] ?? "").toLowerCase();
      let filename = headerFilename(req, "translation.txt");
      let translationBytes: Uint8Array;
      if (contentType.includes("application/json")) {
        const b = await body(req) as Record<string, unknown>;
        translationBytes = asBytes(b.bytes);
        filename = String(b.filename ?? filename);
      } else {
        translationBytes = new Uint8Array(await rawBody(req));
      }
      const input = parseDocumentInput(filename, translationBytes);
      const translated = parseManuscript(input.rawText, { sourceFilename: input.filename, sourceFormat: input.format });
      const runDir = join(process.cwd(), "run-artifacts", id);
      mkdirSync(runDir, { recursive: true });
      writeFileSync(join(runDir, `translation-returned.${input.format}`), Buffer.from(translationBytes));
      const report = validateReturnedTranslation(id, translated.chapters);
      return json(res, 200, report);
    }

    if (req.method === "POST" && url.pathname.endsWith("/review") && url.pathname.startsWith("/api/qa/")) {
      const id = url.pathname.split("/").slice(-2, -1)[0]!;
      const b = await body(req) as Record<string, unknown>;
      const status = String(b.status) as "approved" | "rejected" | "intentional" | "manual_review";
      return json(res, 200, setFindingReviewStatus(id, String(b.findingId), status));
    }

    if (req.method === "GET" && url.pathname.startsWith("/api/runs/")) {
      const id = url.pathname.split("/").pop()!; const run = getRun(id); if (!run) return json(res, 404, { error: "Run not found" });
      return json(res, 200, { id: run.id, terms: run.terms, packet: run.packet, qa: run.qa, superdocs: run.superdocs });
    }

    if (req.method === "GET" && url.pathname.startsWith("/api/export/")) {
      const id = url.pathname.split("/").pop()!; const { artifacts } = exportArtifacts(id); const directory = join(process.cwd(), "run-artifacts", id); mkdirSync(directory, { recursive: true });
      for (const [k, v] of Object.entries(artifacts)) writeFileSync(join(directory, `${k}.${k === "cleanSourceHtml" ? "html" : "md"}`), v);
      return json(res, 200, { directory: `run-artifacts/${id}`, files: Object.keys(artifacts) });
    }

    if (req.method === "GET" && url.pathname === "/api/superdocs/status") {
      const configured = Boolean(process.env.SUPERDOCS_API_KEY);
      if (!configured) return json(res, 200, { configured: false, authenticated: false, status: null });
      const probe = await superdocs.probe();
      return json(res, 200, { configured: true, authenticated: probe.authenticated, status: probe.status });
    }

    if (req.method === "POST" && url.pathname.endsWith("/prepare") && url.pathname.startsWith("/api/superdocs/")) {
      const id = url.pathname.split("/").slice(-2, -1)[0]!; const run = getRun(id); if (!run?.packet) return json(res, 404, { error: "Run not found or packet not ready" });
      const b = await body(req) as Record<string, unknown>;
      const instruction = String(b.instruction ?? "Prepare this manuscript for translation while preserving approved protected terminology, documented formatting-carried meaning, chapter structure, and translator-facing guidance.");
      const modelTier = ["core", "turbo", "pro", "max"].includes(String(b.modelTier)) ? String(b.modelTier) as "core" | "turbo" | "pro" | "max" : undefined;
      const thinkingDepth = ["fast", "balanced", "deep"].includes(String(b.thinkingDepth)) ? String(b.thinkingDepth) as "fast" | "balanced" | "deep" : undefined;
      const state = await superdocs.prepareDocument(run.superdocs, run.packet.cleanSourceHtml, `${run.packet.manuscriptTitle || "manuscript"}.html`, instruction, { modelTier, thinkingDepth });
      updateSuperDocsState(id, state);
      const integrity = state.updatedHtml ? packetIntegrity(run.packet.cleanSourceHtml, state.updatedHtml) : null;
      return json(res, 200, { runId: id, superdocs: state, integrity });
    }

    if (req.method === "POST" && url.pathname.endsWith("/refresh") && url.pathname.startsWith("/api/superdocs/")) {
      const id = url.pathname.split("/").slice(-2, -1)[0]!; const run = getRun(id); if (!run) return json(res, 404, { error: "Run not found" });
      const state = await superdocs.refreshJob(run.superdocs); updateSuperDocsState(id, state);
      const integrity = state.updatedHtml && run.packet ? packetIntegrity(run.packet.cleanSourceHtml, state.updatedHtml) : null;
      return json(res, 200, { runId: id, superdocs: state, integrity });
    }

    if (req.method === "POST" && url.pathname.endsWith("/approve") && url.pathname.startsWith("/api/superdocs/")) {
      const id = url.pathname.split("/").slice(-2, -1)[0]!; const run = getRun(id); if (!run) return json(res, 404, { error: "Run not found" });
      const b = await body(req) as Record<string, unknown>;
      const decisions = (Array.isArray(b.decisions) ? b.decisions : []) as ApproveDecision[];
      const state = await superdocs.approve(run.superdocs, decisions); updateSuperDocsState(id, state);
      const integrity = state.updatedHtml && run.packet ? packetIntegrity(run.packet.cleanSourceHtml, state.updatedHtml) : null;
      return json(res, 200, { runId: id, superdocs: state, integrity });
    }

    if (req.method === "GET" && url.pathname.endsWith("/export") && url.pathname.startsWith("/api/superdocs/")) {
      const id = url.pathname.split("/").slice(-2, -1)[0]!; const run = getRun(id); if (!run) return json(res, 404, { error: "Run not found" });
      const blob = await superdocs.exportDocx(run.superdocs); const buffer = Buffer.from(await blob.arrayBuffer());
      res.writeHead(200, { "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "content-disposition": 'attachment; filename="translation-ready-superdocs-reviewed.docx"' }); return res.end(buffer);
    }

    return json(res, 404, { error: "Not found" });
  } catch (error) {
    return json(res, 500, { error: error instanceof Error ? error.message : String(error) });
  }
});

server.listen(port, () => console.log(`Translation-ready Manuscript UI: http://localhost:${port}`));
