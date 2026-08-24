/**
 * The durable record of in-flight and completed operations.
 *
 * node:sqlite because N4 requires the record to survive SIGKILL and R5
 * requires the claim to be atomic, and the runtime gives both for free. The
 * Python implementation uses stdlib sqlite3 for the same reasons; both
 * packages therefore ship with zero runtime dependencies.
 */

import { DatabaseSync } from "node:sqlite";

export const NEW = "new";
export const IN_FLIGHT = "in_flight";
export const SUCCEEDED = "succeeded";
export const FAILED = "failed";
export const UNKNOWN = "unknown";

export type State =
  | typeof NEW
  | typeof IN_FLIGHT
  | typeof SUCCEEDED
  | typeof FAILED
  | typeof UNKNOWN;

const SCHEMA = `
CREATE TABLE IF NOT EXISTS operations (
    key         TEXT PRIMARY KEY,
    state       TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    job_id      TEXT,
    detail      TEXT,
    owner_pid   INTEGER,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
`;

export interface Record {
  key: string;
  state: State;
  attempts: number;
  result: unknown;
  jobId: string | null;
  detail: string | null;
  ownerPid: number | null;
  ownedByThisProcess: boolean;
}

export class Store {
  readonly path: string;
  private readonly db: DatabaseSync;

  constructor(path: string) {
    this.path = path;
    this.db = new DatabaseSync(path);
    // busy_timeout FIRST, and the order is the whole point.
    //
    // node:sqlite sets no busy timeout by default, where Python's sqlite3 takes
    // one as a connect argument and therefore has it in force before any
    // statement runs. Setting journal_mode=WAL needs an exclusive lock, so with
    // no timeout yet in force it throws "database is locked" the moment two
    // processes open the same database at once — before the schema even exists.
    //
    // Found by running twelve processes at one key. The safety property held
    // throughout (applies stayed at 1: the contended caller failed closed
    // rather than double-applying), but the two implementations behaved
    // differently under the same fault, which is exactly what writing the
    // second one is for. Matched to the Python client's own 10s timeout.
    this.db.exec("PRAGMA busy_timeout = 10000");
    // WAL is a throughput choice, not the correctness mechanism — the atomic
    // claim comes from BEGIN IMMEDIATE and the primary key, both of which hold
    // under any journal mode. Switching to WAL needs an exclusive lock and can
    // report the database busy no matter what the timeout says, so a dozen
    // processes opening the same file at once will sometimes lose this race.
    // Failing the whole client over an optimisation would be the wrong trade.
    // (Surfaced by mutation testing, once the racing children were given a
    // barrier and actually started colliding.)
    try {
      this.db.exec("PRAGMA journal_mode=WAL");
    } catch {
      /* stays in the default journal mode; every guarantee is unaffected */
    }
    this.db.exec(SCHEMA);
  }

  get(key: string): Record | null {
    const row = this.db.prepare("SELECT * FROM operations WHERE key = ?").get(key) as any;
    return row ? Store.toRecord(row) : null;
  }

  stateOf(key: string): State {
    return this.get(key)?.state ?? NEW;
  }

  /**
   * Atomically take ownership of a key. Returns null when the claim succeeded,
   * or the existing record when someone else got there first.
   *
   * BEGIN IMMEDIATE takes the write lock before the read, so two callers racing
   * on the same key cannot both see 'absent' and both insert (SPEC.md R5).
   */
  claim(key: string): Record | null {
    const now = Date.now() / 1000;
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const row = this.db.prepare("SELECT * FROM operations WHERE key = ?").get(key) as any;
      if (row) {
        this.db.exec("COMMIT");
        return Store.toRecord(row);
      }
      this.db
        .prepare(
          "INSERT INTO operations (key, state, attempts, owner_pid, created_at, updated_at)" +
            " VALUES (?, ?, 0, ?, ?, ?)",
        )
        .run(key, IN_FLIGHT, process.pid, now, now);
      this.db.exec("COMMIT");
      return null;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  recordAttempt(key: string): void {
    this.db
      .prepare("UPDATE operations SET attempts = attempts + 1, updated_at = ? WHERE key = ?")
      .run(Date.now() / 1000, key);
  }

  /** Remember key -> jobId the moment a job id is first seen. This is the
   * binding reconciliation depends on; recording it late is how a timeout ends
   * up with nothing to ask the server about (SPEC.md 6). */
  bindJob(key: string, jobId: string): void {
    this.update(key, { job_id: jobId });
  }

  succeed(key: string, result: unknown): void {
    this.update(key, { state: SUCCEEDED, result_json: JSON.stringify(result ?? null), detail: null });
  }

  fail(key: string, detail: string): void {
    this.update(key, { state: FAILED, detail });
  }

  markUnknown(key: string, detail: string): void {
    this.update(key, { state: UNKNOWN, detail });
  }

  /**
   * Drop the record entirely, returning the key to NEW.
   *
   * Only ever called after a retryable outcome, which the table guarantees
   * means provably not applied (SPEC.md R10). Releasing a key that might have
   * been applied would be the double-apply.
   */
  release(key: string): void {
    this.db.prepare("DELETE FROM operations WHERE key = ?").run(key);
  }

  keys(): string[] {
    return (this.db.prepare("SELECT key FROM operations").all() as any[]).map((r) => r.key);
  }

  private update(key: string, fields: SQLFields): void {
    const withStamp: SQLFields = { ...fields, updated_at: Date.now() / 1000 };
    const names = Object.keys(withStamp);
    const assigns = names.map((n) => `${n} = ?`).join(", ");
    this.db
      .prepare(`UPDATE operations SET ${assigns} WHERE key = ?`)
      .run(...names.map((n) => withStamp[n] as any), key);
  }

  private static toRecord(row: any): Record {
    return {
      key: row.key,
      state: row.state,
      attempts: row.attempts,
      result: row.result_json === null ? null : JSON.parse(row.result_json),
      jobId: row.job_id,
      detail: row.detail,
      ownerPid: row.owner_pid,
      ownedByThisProcess: row.owner_pid === process.pid,
    };
  }
}

type SQLFields = { [column: string]: string | number | null };
