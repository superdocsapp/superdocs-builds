import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RunStore } from "./runStore.js";

let dir;

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "svcflow-runs-"));
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

const settle = () => new Promise((resolve) => setTimeout(resolve, 700));
const change = { id: "x", number: "CHG0010042", configuration_item: "PROD-API-GATEWAY-01" };

describe("RunStore in memory", () => {
  it("bounds itself, evicting the oldest run first", () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 2, statePath: null });

    store.create("a", { change });
    store.create("b", { change });
    store.create("c", { change });

    expect(store.size).toBe(2);
    expect(store.get("a")).toBeNull();
    expect(store.get("c")).not.toBeNull();
  });

  it("expires a run past its TTL on read", () => {
    const store = new RunStore({ ttlMs: 5, limit: 10, statePath: null });
    const run = store.create("a", { change });
    run.updatedAt = Date.now() - 1000;

    expect(store.get("a")).toBeNull();
  });

  it("sweeps expired runs and leaves live ones", () => {
    const store = new RunStore({ ttlMs: 5, limit: 10, statePath: null });

    const stale = store.create("stale", { change });
    stale.updatedAt = Date.now() - 1000;
    store.create("fresh", { change });

    expect(store.sweep()).toBe(1);
    expect(store.size).toBe(1);
    expect(store.get("fresh")).not.toBeNull();
  });

  it("appends audit events in order", () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: null });
    const run = store.create("a", { change });

    store.record(run, "uploaded", { chunks: 23 });
    store.record(run, "exported", { bytes: 100 });

    expect(run.audit.map((event) => event.type)).toEqual(["uploaded", "exported"]);
    expect(run.audit[0].chunks).toBe(23);
  });
});

describe("RunStore persistence", () => {
  /**
   * One file per run. The whole point of the layout: saving a change to one
   * review must not re-serialize every other open review.
   */
  it("writes one file per run, not one file for everything", async () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });

    store.create("alpha", { change });
    store.create("beta", { change });
    await settle();

    expect(fs.readdirSync(dir).sort()).toEqual(["alpha.json", "beta.json"]);
  });

  it("only rewrites the run that changed", async () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });

    store.create("alpha", { change });
    const beta = store.create("beta", { change });
    await settle();

    const untouched = fs.statSync(path.join(dir, "alpha.json")).mtimeMs;

    store.record(beta, "exported", {});
    await settle();

    expect(fs.statSync(path.join(dir, "alpha.json")).mtimeMs).toBe(untouched);
    expect(JSON.parse(fs.readFileSync(path.join(dir, "beta.json"), "utf8")).audit).toHaveLength(1);
  });

  it("restores runs into a fresh store", async () => {
    const first = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    const run = first.create("alpha", { change, filename: "a.docx" });
    first.record(run, "uploaded", {});
    first.flush();

    const second = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    const restored = second.get("alpha");

    expect(restored).not.toBeNull();
    expect(restored.filename).toBe("a.docx");
    expect(restored.change.number).toBe("CHG0010042");
    expect(restored.audit).toHaveLength(1);
  });

  it("drops expired runs from disk on restore", () => {
    const first = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    const run = first.create("old", { change });
    run.updatedAt = Date.now() - 10_000;
    first.flush();

    const second = new RunStore({ ttlMs: 1000, limit: 10, statePath: dir });

    expect(second.get("old")).toBeNull();
    expect(fs.existsSync(path.join(dir, "old.json"))).toBe(false);
  });

  it("removes the file when a run is evicted", async () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 1, statePath: dir });

    store.create("first", { change });
    store.create("second", { change });
    await settle();

    expect(fs.existsSync(path.join(dir, "first.json"))).toBe(false);
    expect(fs.existsSync(path.join(dir, "second.json"))).toBe(true);
  });

  /** One corrupt file must not cost every other open review. */
  it("discards an unreadable run and restores the rest", () => {
    const first = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    first.create("good", { change });
    first.flush();

    fs.writeFileSync(path.join(dir, "broken.json"), "{ not json", "utf8");

    const second = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });

    expect(second.get("good")).not.toBeNull();
    expect(fs.existsSync(path.join(dir, "broken.json"))).toBe(false);
  });

  it("flushes pending writes synchronously on shutdown", () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    store.create("alpha", { change });

    // No settle: flush has to land it without waiting for the debounce.
    store.flush();

    expect(fs.existsSync(path.join(dir, "alpha.json"))).toBe(true);
  });

  /**
   * Shutting down before the first background write is the case where losing
   * state would hurt most: the directory does not exist yet.
   */
  it("creates the state directory when flushing into a fresh location", () => {
    const fresh = path.join(dir, "nested", "state");
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: fresh });

    store.create("alpha", { change });
    store.flush();

    expect(fs.existsSync(path.join(fresh, "alpha.json"))).toBe(true);
  });

  /** Session ids become filenames, so they are validated rather than trusted. */
  it("refuses a session id that would escape the state directory", () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });

    expect(() => store.create("../escape", { change })).toThrow(/Unsafe session id/u);
    expect(() => store.create("a/b", { change })).toThrow(/Unsafe session id/u);
    expect(store.size).toBe(0);
    expect(fs.existsSync(path.join(path.dirname(dir), "escape.json"))).toBe(false);
  });

  it("accepts the session ids the workflow actually mints", () => {
    const store = new RunStore({ ttlMs: 60_000, limit: 10, statePath: dir });
    expect(() => store.create("svcflow-chg0010042-mt5heq7s", { change })).not.toThrow();
  });
});
