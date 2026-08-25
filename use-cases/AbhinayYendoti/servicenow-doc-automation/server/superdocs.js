/**
 * SuperDocs API client.
 *
 * This is the only place the app talks to SuperDocs. Every call is a live HTTP
 * request unless the cassette transport is explicitly in replay mode, and the
 * cassette only ever serves bytes a real run recorded — there is no
 * hand-written fake.
 *
 * Contract (verified against https://api.superdocs.app/openapi.json):
 *
 *   account   GET  /v1/agents/whoami                  tier + monthly quota
 *   upload    POST /v1/documents/upload-base64
 *   edit      POST /v1/chat/async                     -> job_id
 *   progress  GET  /v1/chat/{session_id}/stream       SSE
 *             GET  /v1/jobs/{job_id}                  polling fallback
 *   approve   POST /v1/chat/{session_id}/approve      one change or a batch
 *   continue  POST /v1/chat/{session_id}/continue     large-edit pause
 *   re-edit   POST /v1/sessions/{sid}/chunks/{cid}/re-edit
 *   history   GET  /v1/sessions/{session_id}/history
 *   export    POST /v1/documents/export               returns file bytes
 */

import { Cassette, interactionKey } from "./cassette.js";
import { log } from "./log.js";

const DEFAULT_BASE_URL = "https://api.superdocs.app";
const DEFAULT_TIMEOUT_MS = 120_000;
const MAX_RETRIES = 2;

/**
 * Job statuses that mean the job will not change again on its own. `failed` and
 * `cancelled` are terminal too — terminal is not the same as successful, and
 * conflating them is how a failed run reports as finished.
 */
export const TERMINAL_STATUSES = new Set(["completed", "succeeded", "success", "done", "failed", "cancelled"]);
export const FAILED_STATUSES = new Set(["failed", "cancelled"]);

export class SuperDocsError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "SuperDocsError";
    this.status = status;
    this.body = body;
  }
}

let settings = { apiKey: "", baseUrl: DEFAULT_BASE_URL, configured: false, replayMode: "off" };
let cassette = new Cassette({ mode: "off" });

export function configureSuperDocs(config) {
  settings = {
    apiKey: config.apiKey,
    baseUrl: config.baseUrl || DEFAULT_BASE_URL,
    configured: config.configured,
    replayMode: config.replayMode ?? "off"
  };

  cassette = new Cassette({ mode: settings.replayMode, dir: config.cassetteDir });

  if (cassette.enabled) {
    log.warn("SuperDocs cassette transport active", {
      mode: cassette.mode,
      interactions: cassette.size
    });
  }

  return settings;
}

export function superDocsConfig() {
  return { ...settings, replaying: cassette.mode === "replay", recording: cassette.mode === "record" };
}

async function call(path, { method = "GET", json, timeoutMs = DEFAULT_TIMEOUT_MS, raw = false } = {}) {
  const key = interactionKey(method, path, json);

  if (cassette.mode === "replay") {
    const recorded = cassette.replay(key);

    if (!recorded) {
      throw new SuperDocsError(
        `Replay mode is on but nothing was recorded for ${method} ${path}. Re-record with SUPERDOCS_REPLAY=record.`,
        0,
        null
      );
    }

    if (recorded.status >= 400) {
      throw new SuperDocsError(
        `SuperDocs ${method} ${path} failed with ${recorded.status} (replayed)`,
        recorded.status,
        recorded.body.toString("utf8").slice(0, 600)
      );
    }

    return finish(recorded.body, recorded.contentType, raw);
  }

  if (!settings.configured) {
    throw new SuperDocsError(
      "SUPERDOCS_API_KEY is not set. This app talks to the real SuperDocs API and has no offline fallback.",
      0,
      null
    );
  }

  const url = `${settings.baseUrl}${path}`;
  const startedAt = Date.now();
  let lastError;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const headers = { Accept: "application/json", Authorization: `Bearer ${settings.apiKey}` };

      if (json !== undefined) headers["Content-Type"] = "application/json";
      // A retry must not be able to bill a second operation.
      if (method === "POST") headers["Idempotency-Key"] = `req_${crypto.randomUUID()}`;

      const response = await fetch(url, {
        method,
        headers,
        body: json === undefined ? undefined : JSON.stringify(json),
        signal: AbortSignal.timeout(timeoutMs)
      });

      const body = Buffer.from(await response.arrayBuffer());
      const contentType = response.headers.get("content-type");

      if (!response.ok) {
        const retryable = response.status === 429 || response.status >= 500;

        if (retryable && attempt < MAX_RETRIES) {
          log.warn("superdocs retrying", { path, status: response.status, attempt });
          await sleep(500 * 2 ** attempt);
          continue;
        }

        cassette.record(key, { status: response.status, contentType, body });

        throw new SuperDocsError(
          `SuperDocs ${method} ${path} failed with ${response.status}`,
          response.status,
          body.toString("utf8").slice(0, 600)
        );
      }

      cassette.record(key, { status: response.status, contentType, body });
      log.debug("superdocs call", { method, path, status: response.status, ms: Date.now() - startedAt });

      return finish(body, contentType, raw);
    } catch (error) {
      lastError = error;
      if (error instanceof SuperDocsError || attempt >= MAX_RETRIES) throw error;
      await sleep(500 * 2 ** attempt);
    }
  }

  throw lastError ?? new SuperDocsError("SuperDocs request failed.", 0, null);
}

function finish(body, contentType, raw) {
  if (raw) return { bytes: body, contentType };
  const text = body.toString("utf8");
  return text ? JSON.parse(text) : null;
}

/**
 * Tier and remaining monthly operations. Cheap, unmetered, and the only way to
 * know before starting a run whether it can finish — a run that dies halfway
 * through for quota is worse than one that never started.
 */
export async function whoami() {
  return call("/v1/agents/whoami", { method: "GET", timeoutMs: 15_000 });
}

/** upload: push the mapped source document into a SuperDocs session. */
export async function uploadDocument({ sessionId, filename, content }) {
  return call("/v1/documents/upload-base64", {
    method: "POST",
    json: {
      filename,
      file_base64: Buffer.from(content, "utf8").toString("base64"),
      session_id: sessionId,
      return_html: true
    }
  });
}

/**
 * edit: ask SuperDocs to rewrite the uploaded document.
 *
 * `approval_mode: "ask_every_time"` is what makes this human-in-the-loop: the
 * job parks at `awaiting_approval` with a batch of proposed chunk changes
 * rather than applying them.
 */
export async function requestEdit({ sessionId, message, documentHtml, modelTier, thinkingDepth }) {
  return call("/v1/chat/async", {
    method: "POST",
    json: {
      message,
      session_id: sessionId,
      approval_mode: "ask_every_time",
      response_mode: "full",
      ...(modelTier ? { model_tier: modelTier } : {}),
      ...(thinkingDepth ? { thinking_depth: thinkingDepth } : {}),
      ...(documentHtml ? { document_html: documentHtml } : {})
    }
  });
}

export async function getJob(jobId) {
  return call(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: "GET", timeoutMs: 30_000 });
}

/** approve: one human decision, recorded by SuperDocs against the proposed change. */
export async function approveChange({ sessionId, jobId, changeId, approved, feedback }) {
  return call(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
    method: "POST",
    json: {
      job_id: jobId,
      approved,
      ...(changeId ? { change_id: changeId } : {}),
      ...(feedback ? { feedback } : {})
    }
  });
}

/**
 * Batch form of the same endpoint. Deciding a batch of twelve changes is one
 * round trip, not twelve — and the decisions land together, so the job cannot
 * resume half-decided.
 */
export async function approveChanges({ sessionId, jobId, changes }) {
  return call(`/v1/chat/${encodeURIComponent(sessionId)}/approve`, {
    method: "POST",
    json: {
      job_id: jobId,
      // Required by the schema even in batch form; the per-change flags win.
      approved: changes.every((change) => change.approved),
      changes: changes.map(({ changeId, approved, feedback }) => ({
        change_id: changeId,
        approved,
        ...(feedback ? { feedback } : {})
      }))
    }
  });
}

/**
 * A large edit can pause to ask whether to keep going. That pause also reports
 * `status: "awaiting_approval"`, distinguished only by
 * `metadata.awaiting_kind === "continue_prompt"`, and it is resolved here — not
 * by the approve endpoint. Treating it as a change batch parks the job forever.
 */
export async function continueJob({ sessionId, jobId, keepGoing = true }) {
  return call(`/v1/chat/${encodeURIComponent(sessionId)}/continue`, {
    method: "POST",
    json: { job_id: jobId, continue: keepGoing }
  });
}

/**
 * Re-apply the model's intent to one section on top of the text that is
 * actually there. Used after a rejection: the reviewer says why the change was
 * wrong and SuperDocs rewrites that section alone.
 *
 * Bills one operation.
 */
export async function reEditChunk({ sessionId, chunkId, currentHtml, proposedHtml, originalHtml, explanation, mode = "redo" }) {
  return call(
    `/v1/sessions/${encodeURIComponent(sessionId)}/chunks/${encodeURIComponent(chunkId)}/re-edit`,
    {
      method: "POST",
      json: {
        user_current_html: currentHtml,
        ...(originalHtml ? { ai_original_old_html: originalHtml } : {}),
        ...(proposedHtml ? { ai_proposed_new_html: proposedHtml } : {}),
        ...(explanation ? { ai_explanation: explanation } : {}),
        mode
      }
    }
  );
}

export async function getSessionHistory(sessionId, { includeDocumentHtml = false } = {}) {
  return call(
    `/v1/sessions/${encodeURIComponent(sessionId)}/history?include_document_html=${includeDocumentHtml}`,
    { method: "GET", timeoutMs: 30_000 }
  );
}

/**
 * export: render the approved SuperDocs document.
 *
 * The filename goes in `options` — the top-level `filename` field is retained
 * only for legacy callers and `options.filename` wins when both are set.
 * Answers with the file itself, so the body is read raw.
 */
export async function exportDocument({ sessionId, format = "docx", filename, sourceFilename }) {
  const base = filename?.replace(/\.[^.]+$/u, "");

  return call("/v1/documents/export", {
    method: "POST",
    raw: true,
    json: {
      session_id: sessionId,
      format,
      ...(base ? { options: { filename: base } } : {}),
      ...(sourceFilename ? { source_filename: sourceFilename } : {})
    }
  });
}

/**
 * Server-Sent Events for one chat job.
 *
 * Yields parsed events as they arrive. The caller keeps a polling fallback:
 * SSE is the nicer path, not the only one, and a dropped connection must not
 * strand a review.
 */
export async function* streamChat({ sessionId, jobId, signal }) {
  if (cassette.mode === "replay") return;

  const url = `${settings.baseUrl}/v1/chat/${encodeURIComponent(sessionId)}/stream?job_id=${encodeURIComponent(jobId)}`;

  const response = await fetch(url, {
    headers: { Accept: "text/event-stream", Authorization: `Bearer ${settings.apiKey}` },
    signal
  });

  if (!response.ok || !response.body) {
    throw new SuperDocsError(`SuperDocs stream failed with ${response.status}`, response.status, null);
  }

  const decoder = new TextDecoder();
  let buffer = "";

  for await (const chunk of response.body) {
    buffer += decoder.decode(chunk, { stream: true });

    // SSE frames are separated by a blank line; anything after the last one is
    // a partial frame and has to stay in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const event = parseFrame(frame);
      if (event) yield event;
    }
  }
}

function parseFrame(frame) {
  let name = "message";
  const data = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }

  if (!data.length) return null;

  const payload = data.join("\n");
  try {
    return { event: name, data: JSON.parse(payload) };
  } catch {
    return { event: name, data: payload };
  }
}

export async function health() {
  const response = await fetch(`${settings.baseUrl}/health`, { signal: AbortSignal.timeout(10_000) });
  return response.json();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
