import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { promises as fs } from "node:fs";
import { loadState } from "./state.js";

export type ReviewDecision = "approve" | "reject";

export interface ReviewRecord {
  blockId: string;
  decision: ReviewDecision;
  decidedAt: string;
}

export interface ReviewServerOptions {
  statePath: string;
  port?: number;
  host?: string;
}

export async function startReviewServer(options: ReviewServerOptions): Promise<Server> {
  const server = createServer(async (request, response) => {
    try {
      await handleRequest(request, response, options.statePath);
    } catch (error) {
      sendJson(response, 500, { error: error instanceof Error ? error.message : String(error) });
    }
  });
  await new Promise<void>((resolve) => server.listen(options.port ?? 4173, options.host ?? "127.0.0.1", resolve));
  return server;
}

async function handleRequest(request: IncomingMessage, response: ServerResponse, statePath: string): Promise<void> {
  const method = request.method ?? "GET";
  const url = new URL(request.url ?? "/", "http://localhost");
  if (method === "GET" && url.pathname === "/") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(reviewHtml());
    return;
  }
  if (method === "GET" && url.pathname === "/api/state") {
    const state = await loadState(statePath);
    const reviews = await loadReviews(statePath);
    sendJson(response, 200, { ...state, reviews });
    return;
  }
  if (method === "POST" && url.pathname === "/api/review") {
    const body = await readJson(request);
    const blockId = typeof body.blockId === "string" ? body.blockId : "";
    const decision = body.decision === "approve" || body.decision === "reject" ? body.decision : undefined;
    if (!blockId || !decision) {
      sendJson(response, 400, { error: "blockId and decision (approve|reject) are required." });
      return;
    }
    try {
      sendJson(response, 200, await recordReview(statePath, blockId, decision));
    } catch (error) {
      sendJson(response, 404, { error: error instanceof Error ? error.message : String(error) });
    }
    return;
  }
  response.writeHead(404);
  response.end("Not found");
}

export async function recordReview(
  statePath: string,
  blockId: string,
  decision: ReviewDecision,
): Promise<ReviewRecord> {
  const state = await loadState(statePath);
  if (!state.paper.blocks.some((block) => block.id === blockId)) {
    throw new Error(`Unknown paper block: ${blockId}`);
  }
  const reviews = await loadReviews(statePath);
  const next = reviews.filter((review) => review.blockId !== blockId);
  const record = { blockId, decision, decidedAt: new Date().toISOString() };
  next.push(record);
  await saveReviews(statePath, next);
  return record;
}

async function loadReviews(statePath: string): Promise<ReviewRecord[]> {
  try {
    return JSON.parse(await fs.readFile(`${statePath}.reviews.json`, "utf8")) as ReviewRecord[];
  } catch {
    return [];
  }
}

async function saveReviews(statePath: string, reviews: ReviewRecord[]): Promise<void> {
  const reviewPath = `${statePath}.reviews.json`;
  const temporaryPath = `${reviewPath}.tmp-${process.pid}-${Date.now()}`;
  await fs.writeFile(temporaryPath, JSON.stringify(reviews, null, 2), "utf8");
  await fs.rename(temporaryPath, reviewPath);
}

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  const value: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(value));
}

function reviewHtml(): string {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>Notebook Paper Review</title>
<style>body{font:16px system-ui;margin:2rem;background:#f6f7f9;color:#18202a}main{max-width:900px;margin:auto}.block{background:white;border:1px solid #d9dee7;border-radius:8px;padding:1rem;margin:1rem 0}.content{white-space:pre-wrap;background:#f1f3f5;padding:.75rem;border-radius:5px}.actions{display:flex;gap:.5rem;margin-top:.75rem}button{padding:.5rem .8rem;border:0;border-radius:4px;cursor:pointer}.approve{background:#16803c;color:white}.reject{background:#b42318;color:white}.decision{margin-left:.5rem;font-weight:600}</style></head>
<body><main><h1>Notebook Paper Review</h1><p>Review each generated block before it is accepted.</p><section id="app">Loading…</section></main>
<script>
async function load(){const r=await fetch('/api/state');const s=await r.json();const root=document.querySelector('#app');root.innerHTML='';for(const b of s.paper.blocks){const d=(s.reviews||[]).find(x=>x.blockId===b.id);const el=document.createElement('article');el.className='block';el.innerHTML='<h2>'+escapeHtml(b.type)+' <code>'+escapeHtml(b.id)+'</code></h2><div class="content">'+escapeHtml(b.content)+'</div><div class="actions"><button class="approve">Approve</button><button class="reject">Reject</button><span class="decision">'+(d?d.decision:'Pending')+'</span></div>';el.querySelector('.approve').onclick=()=>decide(b.id,'approve');el.querySelector('.reject').onclick=()=>decide(b.id,'reject');root.appendChild(el)}}
async function decide(blockId,decision){await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blockId,decision})});load()}
function escapeHtml(v){return v.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}load();
</script></body></html>`;
}
