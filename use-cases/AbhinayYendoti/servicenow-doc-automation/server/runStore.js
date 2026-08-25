/**
 * Server-side record of each document run.
 *
 * The browser holds a session id and nothing else that matters: the ServiceNow
 * change a session maps to, the decisions taken and the approval state are kept
 * here, because verification and export must not trust values echoed back by a
 * client.
 *
 * Three things this fixes over a bare Map:
 *   - runs expire (TTL) and the store is bounded (oldest evicted first), so a
 *     long-lived process does not grow without limit;
 *   - runs survive a restart, so a deploy mid-review does not strand a reviewer
 *     holding a session id the server has never heard of;
 *   - every run carries an append-only audit trail.
 *
 * Persistence is one file per run, written asynchronously.
 *
 * It was one file for everything, serialized and written synchronously on every
 * mutation. Runs carry document HTML, so that meant re-serializing every open
 * review to save a change to one of them — measured at ~10ms of blocked event
 * loop per persist with 100 runs open, on a path that fires on every poll.
 * Making the write async barely helped, because the cost was JSON.stringify,
 * not the disk. Writing only the run that changed removes the work instead of
 * moving it.
 */

import fs from "node:fs";
import path from "node:path";

import { log } from "./log.js";

const PERSIST_DEBOUNCE_MS = 400;

/** Session ids reach the filesystem, so they are checked, not trusted. */
const SAFE_SESSION_ID = /^[A-Za-z0-9._-]{1,128}$/u;

export class RunStore {
  #runs = new Map();
  #ttlMs;
  #limit;
  #dir;
  #dirty = new Set();
  #removed = new Set();
  #writeTimer = null;
  #writing = false;

  constructor({ ttlMs, limit, statePath } = {}) {
    this.#ttlMs = ttlMs ?? 60 * 60 * 1000;
    this.#limit = limit ?? 200;
    this.#dir = statePath ? path.resolve(statePath) : null;
    this.#restore();
  }

  create(sessionId, seed) {
    // Session ids become filenames. Checked here rather than at write time, so
    // the invariant is "every run in the store is persistable" and a bad id
    // fails loudly at the call site instead of being swallowed by a write.
    if (!SAFE_SESSION_ID.test(sessionId)) {
      throw new Error(`Unsafe session id: ${sessionId}`);
    }

    const now = Date.now();
    const run = {
      sessionId,
      createdAt: now,
      updatedAt: now,
      decisions: {},
      proposals: {},
      audit: [],
      approved: false,
      completed: false,
      ...seed
    };

    this.#runs.set(sessionId, run);
    this.#evict();
    this.#touch(run);
    return run;
  }

  get(sessionId) {
    const run = this.#runs.get(sessionId);
    if (!run) return null;

    if (Date.now() - run.updatedAt > this.#ttlMs) {
      this.#forget(sessionId);
      return null;
    }

    return run;
  }

  /** Mutate through here so persistence and the TTL clock stay honest. */
  update(run, mutate) {
    mutate(run);
    this.#touch(run);
    return run;
  }

  /**
   * Append-only run history. This is what the UI shows as the audit trail and
   * what a reviewer would be asked for if the export were ever questioned.
   */
  record(run, type, detail = {}) {
    const event = { at: new Date().toISOString(), type, ...detail };
    run.audit.push(event);
    this.#touch(run);
    return event;
  }

  get size() {
    return this.#runs.size;
  }

  /** Drop expired runs. Called on a timer by the server. */
  sweep() {
    const cutoff = Date.now() - this.#ttlMs;
    let removed = 0;

    for (const [sessionId, run] of this.#runs) {
      if (run.updatedAt < cutoff) {
        this.#forget(sessionId);
        removed += 1;
      }
    }

    if (removed) log.info("run store swept", { removed, remaining: this.#runs.size });
    return removed;
  }

  /** Shutdown only. The process is leaving, so these have to block. */
  flush() {
    if (this.#writeTimer) {
      clearTimeout(this.#writeTimer);
      this.#writeTimer = null;
    }

    if (!this.#dir) return;

    try {
      // The async path creates this lazily; a shutdown before the first
      // background write would otherwise have nowhere to put the state.
      fs.mkdirSync(this.#dir, { recursive: true });
    } catch (error) {
      log.warn("could not create run state directory", { detail: String(error.message ?? error) });
      return;
    }

    for (const sessionId of this.#removed) {
      try {
        fs.rmSync(this.#pathFor(sessionId), { force: true });
      } catch {
        /* leaving anyway */
      }
    }
    this.#removed.clear();

    for (const sessionId of this.#dirty) {
      const run = this.#runs.get(sessionId);
      if (!run) continue;

      try {
        fs.writeFileSync(this.#pathFor(sessionId), JSON.stringify(run), "utf8");
      } catch (error) {
        log.warn("could not persist run state", { detail: String(error.message ?? error) });
      }
    }
    this.#dirty.clear();
  }

  #touch(run) {
    run.updatedAt = Date.now();
    if (!this.#dir) return;

    this.#dirty.add(run.sessionId);
    this.#removed.delete(run.sessionId);
    this.#persistSoon();
  }

  #forget(sessionId) {
    this.#runs.delete(sessionId);
    if (!this.#dir) return;

    this.#dirty.delete(sessionId);
    this.#removed.add(sessionId);
    this.#persistSoon();
  }

  #evict() {
    while (this.#runs.size > this.#limit) {
      // Map iterates in insertion order, so the first key is the oldest run.
      const oldest = this.#runs.keys().next().value;
      this.#forget(oldest);
      log.warn("run store at capacity, evicted oldest run", { sessionId: oldest });
    }
  }

  #pathFor(sessionId) {
    if (!SAFE_SESSION_ID.test(sessionId)) {
      throw new Error(`Refusing to persist a run with an unsafe session id: ${sessionId}`);
    }
    return path.join(this.#dir, `${sessionId}.json`);
  }

  #persistSoon() {
    if (this.#writeTimer || this.#writing) return;

    this.#writeTimer = setTimeout(() => {
      this.#writeTimer = null;
      void this.#write();
    }, PERSIST_DEBOUNCE_MS);
    this.#writeTimer.unref?.();
  }

  /**
   * Persist whatever changed since the last write, one batch at a time.
   * Anything that changes while a write is in flight is picked up by the next.
   */
  async #write() {
    if (!this.#dir || this.#writing) return;

    const dirty = [...this.#dirty];
    const removed = [...this.#removed];
    if (!dirty.length && !removed.length) return;

    this.#dirty.clear();
    this.#removed.clear();
    this.#writing = true;

    try {
      await fs.promises.mkdir(this.#dir, { recursive: true });

      await Promise.all(
        removed.map((sessionId) =>
          fs.promises.rm(this.#pathFor(sessionId), { force: true }).catch(() => {})
        )
      );

      await Promise.all(
        dirty.map(async (sessionId) => {
          const run = this.#runs.get(sessionId);
          if (!run) return;

          // Write-then-rename: a crash mid-write leaves the previous state
          // intact rather than a truncated file that fails to parse on boot.
          const file = this.#pathFor(sessionId);
          const temporary = `${file}.tmp`;
          await fs.promises.writeFile(temporary, JSON.stringify(run), "utf8");
          await fs.promises.rename(temporary, file);
        })
      );
    } catch (error) {
      log.warn("could not persist run state", { detail: String(error.message ?? error) });
    } finally {
      this.#writing = false;
      if (this.#dirty.size || this.#removed.size) this.#persistSoon();
    }
  }

  #restore() {
    if (!this.#dir || !fs.existsSync(this.#dir)) return;

    const cutoff = Date.now() - this.#ttlMs;
    let restored = 0;
    let expired = 0;

    let entries;
    try {
      entries = fs.readdirSync(this.#dir).filter((name) => name.endsWith(".json"));
    } catch (error) {
      log.warn("could not read run state directory, starting empty", {
        detail: String(error.message ?? error)
      });
      return;
    }

    for (const name of entries) {
      const file = path.join(this.#dir, name);

      try {
        const run = JSON.parse(fs.readFileSync(file, "utf8"));

        if (run?.sessionId && run.updatedAt >= cutoff) {
          this.#runs.set(run.sessionId, run);
          restored += 1;
        } else {
          fs.rmSync(file, { force: true });
          expired += 1;
        }
      } catch (error) {
        // One unreadable run must not stop the rest from coming back.
        log.warn("discarding unreadable run state", { file: name, detail: String(error.message ?? error) });
        fs.rmSync(file, { force: true });
      }
    }

    if (restored || expired) log.info("run state restored", { runs: restored, expired });
  }
}
