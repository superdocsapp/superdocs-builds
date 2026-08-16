import { promises as fs } from "node:fs";

const activeLocks = new Set<string>();
import type { EvidenceSnapshot, PaperDocument } from "./types.js";

export interface ProjectState {
  snapshot: EvidenceSnapshot;
  paper: PaperDocument;
}

export async function saveState(path: string, state: ProjectState): Promise<void> {
  const lockPath = `${path}.lock`;
  const lockHandle = await acquireExclusiveLock(lockPath, path);

  const temporaryPath = `${path}.tmp-${process.pid}-${Date.now()}`;
  try {
    await fs.writeFile(temporaryPath, JSON.stringify(state, null, 2), "utf8");
    await fs.rename(temporaryPath, path);
  } finally {
    await lockHandle.close();
    await fs.rm(lockPath, { force: true });
  }
}

export async function acquireExclusiveLock(lockPath: string, label: string): Promise<import("node:fs/promises").FileHandle> {
  const lockContents = JSON.stringify({ pid: process.pid, createdAt: Date.now() });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const handle = await fs.open(lockPath, "wx");
      await handle.writeFile(lockContents, "utf8");
      activeLocks.add(lockPath);
      return handle;
    } catch (error) {
      if (attempt > 0 || !(error instanceof Error && "code" in error && error.code === "EEXIST")) {
        throw new Error(`Resource is already locked: ${label}`, { cause: error });
      }
      if (!(await isStaleLock(lockPath))) {
        throw new Error(`Resource is already locked: ${label}`);
      }
      await fs.rm(lockPath, { force: true });
    }
  }
  throw new Error(`Unable to acquire lock: ${label}`);
}

export async function releaseExclusiveLock(lockHandle: import("node:fs/promises").FileHandle, lockPath: string): Promise<void> {
  await lockHandle.close();
  activeLocks.delete(lockPath);
  await fs.rm(lockPath, { force: true });
}

export async function closeExclusiveLock(lockHandle: import("node:fs/promises").FileHandle, lockPath: string): Promise<void> {
  await lockHandle.close();
  activeLocks.delete(lockPath);
}

async function isStaleLock(lockPath: string): Promise<boolean> {
  const staleAfterMs = 10 * 60 * 1000;
  try {
    const stat = await fs.stat(lockPath);
    if (Date.now() - stat.mtimeMs > staleAfterMs) return true;
    const raw = JSON.parse(await fs.readFile(lockPath, "utf8")) as { pid?: number; createdAt?: number };
    if (typeof raw.pid !== "number") return true;
    if (raw.pid === process.pid && !activeLocks.has(lockPath)) return true;
    try {
      process.kill(raw.pid, 0);
      return false;
    } catch {
      return true;
    }
  } catch {
    return false;
  }
}

export async function loadState(path: string): Promise<ProjectState> {
  const text = await fs.readFile(path, "utf8");
  return JSON.parse(text) as ProjectState;
}
