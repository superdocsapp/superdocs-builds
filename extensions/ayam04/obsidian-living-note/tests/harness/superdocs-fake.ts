/**
 * A stand-in SuperDocs service. It parses an uploaded Markdown document into
 * chunked HTML the same way the real API does, applies only the changes that
 * were approved, and exports the result. The end-to-end test therefore checks
 * the plugin against a service that can disagree with it, not against a mock
 * that always says yes.
 */
import { htmlToMarkdown } from "../../src/ownership";
import type { PendingChange } from "../../src/types";
import type { RequestHandler, RequestUrlParam } from "./obsidian";

export interface Chunk {
  chunkId: string;
  text: string;
  html: string;
}

/** Blank-line separated blocks, except inside a fence: what a Markdown parser does. */
export function splitMarkdownBlocks(markdown: string): string[] {
  const blocks: string[] = [];
  let current: string[] = [];
  let fenced = false;
  const flush = (): void => {
    const text = current.join("\n").trim();
    if (text) blocks.push(text);
    current = [];
  };
  for (const line of markdown.split("\n")) {
    if (/^\s{0,3}(```|~~~)/.test(line)) fenced = !fenced;
    if (!fenced && line.trim() === "") flush();
    else current.push(line);
  }
  flush();
  return blocks;
}

export function renderChunks(markdown: string): { html: string; chunks: Chunk[] } {
  const chunks: Chunk[] = [];
  const blocks = splitMarkdownBlocks(markdown);
  blocks.forEach((block, index) => {
    const chunkId = `chunk-${index + 1}`;
    const heading = /^(#{1,6})\s+(.*)$/.exec(block);
    const lines = block.split("\n");
    let html: string;
    if (heading) {
      const level = heading[1].length;
      html = `<h${level} data-chunk-id="${chunkId}">${inline(heading[2])}</h${level}>`;
    } else if (/^\s*(```|~~~)/.test(block)) {
      html = `<pre data-chunk-id="${chunkId}"><code>${lines.slice(1, -1).join("\n")}</code></pre>`;
    } else if (lines.length > 1 && lines.every((line) => line.trim().startsWith("|"))) {
      const rows = lines
        .filter((line) => !/^[\s|:-]+$/.test(line))
        .map((line) => `<tr>${line.split("|").slice(1, -1).map((cell) => `<td>${inline(cell.trim())}</td>`).join("")}</tr>`)
        .join("");
      html = `<table data-chunk-id="${chunkId}"><tbody>${rows}</tbody></table>`;
    } else if (lines.every((line) => /^\s*[-*+]\s+/.test(line))) {
      const items = lines.map((line) => {
        const item = line.replace(/^\s*[-*+]\s+/, "");
        const task = /^\[([ xX])\]\s+(.*)$/.exec(item);
        return task
          ? `<li><input type="checkbox"${task[1] === " " ? "" : " checked"}>${inline(task[2])}</li>`
          : `<li>${inline(item)}</li>`;
      }).join("");
      html = `<ul data-chunk-id="${chunkId}">${items}</ul>`;
    } else if (/^!\[[^\]]*\]\([^)]*\)$/.test(block)) {
      const image = /^!\[([^\]]*)\]\(([^)]*)\)$/.exec(block)!;
      html = `<p data-chunk-id="${chunkId}"><img src="${image[2]}" alt="${image[1]}"></p>`;
    } else {
      html = `<p data-chunk-id="${chunkId}">${inline(block.replace(/\n/g, " "))}</p>`;
    }
    chunks.push({ chunkId, text: block, html });
  });
  return { html: chunks.map((chunk) => chunk.html).join("\n"), chunks };
}

function inline(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_(\S(?:.*?\S)?)_(\s|$)/g, "$1<em>$2</em>$3");
}

export interface FakeOptions {
  /** What the service proposes for the uploaded document. */
  propose: (chunks: Chunk[]) => PendingChange[];
  /** Optional second round, produced after the first round's decisions. */
  proposeAgain?: (chunks: Chunk[], round: number) => PendingChange[];
  /** Corrupt the export to prove the plugin refuses to write on disagreement. */
  corruptExport?: (markdown: string) => string;
  awaitingKind?: string;
  failJob?: string;
}

export interface FakeState {
  documents: Map<string, { markdown: string; chunks: Chunk[] }>;
  attachments: string[];
  messages: string[];
  approvals: Array<{ change_id: string; approved: boolean; feedback?: string }>;
  rounds: number;
}

export function fakeSuperDocs(options: FakeOptions): { handler: RequestHandler; state: FakeState } {
  const state: FakeState = { documents: new Map(), attachments: [], messages: [], approvals: [], rounds: 0 };
  const jobs = new Map<string, { sessionId: string; polls: number; phase: "working" | "review" | "done"; pending: PendingChange[] }>();

  const handler: RequestHandler = async (request: RequestUrlParam) => {
    const body = request.body ? JSON.parse(request.body) as Record<string, string> : {};
    const url = request.url;

    if (url.endsWith("/v1/documents/upload-base64")) {
      const markdown = Buffer.from(body.file_base64, "base64").toString("utf8");
      const rendered = renderChunks(markdown);
      state.documents.set(body.session_id, { markdown, chunks: rendered.chunks });
      return { status: 200, json: { html: rendered.html, chunks_count: rendered.chunks.length } };
    }

    if (url.endsWith("/v1/attachments/upload-base64")) {
      state.attachments.push(body.filename);
      return { status: 200, json: { job_id: `att-${state.attachments.length}`, status: "processing" } };
    }

    if (url.includes("/v1/attachments/status/")) {
      return {
        status: 200,
        json: {
          ready_attachments: state.attachments.map((filename) => ({ filename })),
          processing_jobs: state.attachments.map((filename, index) => ({ job_id: `att-${index + 1}`, filename, status: "completed", error: null })),
          total_processing: 0,
        },
      };
    }

    if (url.endsWith("/v1/chat/async")) {
      state.messages.push(body.message);
      const jobId = `job-${jobs.size + 1}`;
      const document = state.documents.get(body.session_id);
      jobs.set(jobId, { sessionId: body.session_id, polls: 0, phase: "working", pending: options.propose(document?.chunks ?? []) });
      return { status: 200, json: { job_id: jobId, status: "pending" } };
    }

    if (url.includes("/v1/jobs/")) {
      const job = jobs.get(url.split("/v1/jobs/")[1]);
      if (!job) return { status: 404, json: { detail: "no such job" } };
      if (options.failJob) return { status: 200, json: { status: "failed", error: { message: options.failJob } } };
      job.polls++;
      if (job.phase === "done") {
        return { status: 200, json: { status: "completed", usage: { ops_charged: 1, was_billable: true }, result: { response: "done" } } };
      }
      if (job.polls < 2) return { status: 200, json: { status: "in_progress" } };
      job.phase = "review";
      if (options.awaitingKind === "continue_prompt") {
        return { status: 200, json: { status: "awaiting_approval", metadata: { awaiting_kind: "continue_prompt" } } };
      }
      return { status: 200, json: { status: "awaiting_approval", metadata: { pending_changes: job.pending } } };
    }

    if (url.includes("/approve")) {
      const job = jobs.get(body.job_id as unknown as string);
      const decisions = (body as unknown as { changes: Array<{ change_id: string; approved: boolean; feedback?: string }> }).changes;
      state.approvals.push(...decisions);
      state.rounds++;
      if (!job) return { status: 404, json: { detail: "no such job" } };
      const session = state.documents.get(job.sessionId)!;
      for (const decision of decisions) {
        if (!decision.approved) continue;
        const change = job.pending.find((candidate) => candidate.change_id === decision.change_id);
        if (change) applyToFakeDocument(session, change);
      }
      const again = options.proposeAgain?.(session.chunks, state.rounds) ?? [];
      if (again.length) {
        job.pending = again;
        job.phase = "review";
        job.polls = 1;
      } else {
        job.phase = "done";
      }
      return { status: 200, json: { status: "ok", batch_complete: true } };
    }

    if (url.endsWith("/v1/documents/export")) {
      const session = state.documents.get(body.session_id);
      const markdown = session?.markdown ?? "";
      return { status: 200, text: options.corruptExport ? options.corruptExport(markdown) : markdown };
    }

    return { status: 404, json: { detail: `unhandled ${url}` } };
  };

  return { handler, state };
}

function applyToFakeDocument(session: { markdown: string; chunks: Chunk[] }, change: PendingChange): void {
  const blocks = splitMarkdownBlocks(session.markdown);
  const index = session.chunks.findIndex((chunk) => chunk.chunkId === (change.chunk_id ?? change.insert_after_chunk_id ?? change.insert_before_chunk_id));
  if (index < 0) return;
  const replacement = htmlToMarkdown(change.new_html ?? "");
  if (change.operation === "create") blocks.splice(change.insert_after_chunk_id ? index + 1 : index, 0, replacement);
  else if (change.operation === "delete") blocks.splice(index, 1);
  else blocks[index] = replacement;
  session.markdown = `${blocks.join("\n\n")}\n`;
  session.chunks = renderChunks(session.markdown).chunks;
}
