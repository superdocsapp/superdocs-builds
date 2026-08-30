import * as fs from "node:fs";
import * as path from "node:path";

/**
 * Minimal persistence contract the review store depends on. Deliberately
 * key-value + prefix-scan, not a query language — the store owns all
 * indexing/filtering logic; this only owns "does the data survive a
 * restart."
 */
export interface PersistenceBackend {
  get<T>(key: string): T | undefined;
  set<T>(key: string, value: T): void;
  delete(key: string): void;
  listKeys(prefix: string): string[];
}

/** For unit tests — no disk I/O, no VS Code dependency. */
export class InMemoryBackend implements PersistenceBackend {
  private readonly data = new Map<string, unknown>();

  get<T>(key: string): T | undefined {
    return this.data.get(key) as T | undefined;
  }
  set<T>(key: string, value: T): void {
    this.data.set(key, value);
  }
  delete(key: string): void {
    this.data.delete(key);
  }
  listKeys(prefix: string): string[] {
    return [...this.data.keys()].filter((k) => k.startsWith(prefix));
  }
}

/**
 * Real backend: one JSON file per key under `dir`, keys url-encoded to
 * safe filenames. Writes are atomic (write to a temp file, then rename)
 * so a crash mid-write can't leave a half-written, corrupt record — this
 * is the durability guarantee Phase 16/10.5 (extension restart) depends on.
 * No external database dependency, which keeps `npm install` and the
 * fresh-clone test fast and dependency-light.
 */
export class JsonFileBackend implements PersistenceBackend {
  constructor(private readonly dir: string) {
    fs.mkdirSync(dir, { recursive: true });
  }

  private filePath(key: string): string {
    return path.join(this.dir, `${encodeURIComponent(key)}.json`);
  }

  get<T>(key: string): T | undefined {
    try {
      const raw = fs.readFileSync(this.filePath(key), "utf8");
      return JSON.parse(raw) as T;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw err;
    }
  }

  set<T>(key: string, value: T): void {
    const file = this.filePath(key);
    const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
    fs.writeFileSync(tmp, JSON.stringify(value), "utf8");
    fs.renameSync(tmp, file); // atomic on POSIX filesystems
  }

  delete(key: string): void {
    try {
      fs.unlinkSync(this.filePath(key));
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    }
  }

  listKeys(prefix: string): string[] {
    if (!fs.existsSync(this.dir)) return [];
    return fs
      .readdirSync(this.dir)
      .filter((f) => f.endsWith(".json") && !f.includes(".tmp-"))
      .map((f) => decodeURIComponent(f.slice(0, -".json".length)))
      .filter((k) => k.startsWith(prefix));
  }
}
