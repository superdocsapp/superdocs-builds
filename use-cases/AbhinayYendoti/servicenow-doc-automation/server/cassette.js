/**
 * Record/replay transport for the SuperDocs API.
 *
 * SuperDocs is a metered service. Iterating on the review UI should not spend a
 * month of operations re-running the same edit, and CI should not need a live
 * key at all — but a mock hand-written from the docs would only ever prove the
 * app agrees with my reading of the docs.
 *
 * So there is no hand-written mock. `record` captures the real responses of a
 * real run to disk; `replay` serves those exact bytes back. What replays is
 * something the live API actually said.
 *
 * Replay is opt-in (SUPERDOCS_REPLAY), off by default, and the server reports it
 * in /api/health so the UI can label it. A replayed run is never presented as a
 * live one.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { log } from "./log.js";

/** Volatile ids are stripped from the key, or nothing would ever match twice. */
function normalizePath(requestPath) {
  return requestPath
    .replace(/\/v1\/chat\/[^/]+\//u, "/v1/chat/{session}/")
    .replace(/\/v1\/jobs\/[^/?]+/u, "/v1/jobs/{job}")
    .replace(/\/v1\/sessions\/[^/]+/u, "/v1/sessions/{session}");
}

function normalizeBody(json) {
  if (!json || typeof json !== "object") return json;

  const copy = { ...json };
  for (const field of ["session_id", "job_id", "change_id", "filename"]) delete copy[field];

  // The uploaded document is keyed by its content, not its bytes, so a rerun
  // with a different timestamp in the filename still matches.
  if (typeof copy.file_base64 === "string") {
    copy.file_base64 = crypto.createHash("sha256").update(copy.file_base64).digest("hex").slice(0, 16);
  }

  return copy;
}

export function interactionKey(method, requestPath, json) {
  const digest = crypto
    .createHash("sha256")
    .update(JSON.stringify(normalizeBody(json) ?? null))
    .digest("hex")
    .slice(0, 12);

  return `${method} ${normalizePath(requestPath)} ${digest}`;
}

export class Cassette {
  #mode;
  #file;
  #interactions = new Map();
  #cursors = new Map();

  constructor({ mode = "off", dir = "server/cassettes", name = "workflow" } = {}) {
    this.#mode = mode;
    this.#file = path.resolve(dir, `${name}.json`);

    if (mode === "replay") this.#load();
    if (mode === "record") fs.mkdirSync(path.dirname(this.#file), { recursive: true });
  }

  get mode() {
    return this.#mode;
  }

  get enabled() {
    return this.#mode !== "off";
  }

  get size() {
    let total = 0;
    for (const list of this.#interactions.values()) total += list.length;
    return total;
  }

  /**
   * Replay returns the next recorded response for this key. Polling the same
   * job repeatedly is the normal case, and each poll legitimately returns
   * something different, so responses are consumed in the order they were
   * recorded and the last one repeats once exhausted.
   */
  replay(key) {
    const list = this.#interactions.get(key);
    if (!list?.length) return null;

    const cursor = this.#cursors.get(key) ?? 0;
    const index = Math.min(cursor, list.length - 1);
    this.#cursors.set(key, cursor + 1);

    const entry = list[index];
    return {
      status: entry.status,
      contentType: entry.contentType,
      body: Buffer.from(entry.bodyBase64, "base64")
    };
  }

  record(key, { status, contentType, body }) {
    if (this.#mode !== "record") return;

    const list = this.#interactions.get(key) ?? [];
    list.push({
      status,
      contentType,
      bodyBase64: Buffer.from(body).toString("base64"),
      recordedAt: new Date().toISOString()
    });
    this.#interactions.set(key, list);
    this.#save();
  }

  reset() {
    this.#cursors.clear();
  }

  #load() {
    if (!fs.existsSync(this.#file)) {
      log.warn("replay mode is on but no cassette was found", { file: this.#file });
      return;
    }

    try {
      const parsed = JSON.parse(fs.readFileSync(this.#file, "utf8"));
      for (const [key, list] of Object.entries(parsed.interactions ?? {})) {
        this.#interactions.set(key, list);
      }
      log.info("cassette loaded", { file: this.#file, interactions: this.size });
    } catch (error) {
      log.error("could not read cassette", { detail: String(error.message ?? error) });
    }
  }

  #save() {
    try {
      const interactions = Object.fromEntries(this.#interactions);
      fs.writeFileSync(
        this.#file,
        JSON.stringify({ version: 1, recordedAt: new Date().toISOString(), interactions }, null, 2),
        "utf8"
      );
    } catch (error) {
      log.error("could not write cassette", { detail: String(error.message ?? error) });
    }
  }
}
