import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { acquireExclusiveLock, releaseExclusiveLock, saveState } from "../src/state.js";

describe("run and state locking", () => {
  it("rejects a live concurrent lock", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "paper-lock-"));
    const lockPath = path.join(directory, "run.lock");
    const first = await acquireExclusiveLock(lockPath, "test-run");

    await expect(acquireExclusiveLock(lockPath, "test-run")).rejects.toThrow("locked");
    await releaseExclusiveLock(first, lockPath);
  });

  it("recovers a stale lock from a dead process", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "paper-stale-lock-"));
    const statePath = path.join(directory, "state.json");
    const lockPath = `${statePath}.lock`;
    await fs.writeFile(lockPath, JSON.stringify({ pid: 999999, createdAt: 0 }), "utf8");
    const old = new Date(Date.now() - 20 * 60 * 1000);
    await fs.utimes(lockPath, old, old);

    await saveState(statePath, {
      snapshot: { version: "test", notebookPath: "n.ipynb", evidence: [], generatedAt: new Date().toISOString() },
      paper: { title: "Test", blocks: [] },
    });

    expect(await fs.stat(statePath)).toBeTruthy();
  });
});
