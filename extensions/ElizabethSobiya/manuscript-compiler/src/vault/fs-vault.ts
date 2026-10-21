/**
 * A VaultReader backed by the filesystem.
 *
 * Used by the CLI and by the test suite. It mirrors Obsidian's link resolution
 * closely enough that a vault compiles identically inside and outside the app:
 * exact path first, then path plus `.md`, then the shortest unique filename match.
 */

import { readFile, readdir, stat } from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";
import type { VaultReader } from "../core/types";
import { basename, normalizePath, stemOf } from "../core/util";

const SKIP_DIRS = new Set([".git", ".obsidian", "node_modules", ".manuscript-cache", "build"]);

export class FsVault implements VaultReader {
  private index: Map<string, string[]> | null = null;
  private allFiles: string[] = [];

  constructor(private readonly root: string) {}

  private toAbsolute(path: string): string {
    return resolve(this.root, normalizePath(path));
  }

  async readText(path: string): Promise<string> {
    return readFile(this.toAbsolute(path), "utf-8");
  }

  async readBinary(path: string): Promise<Uint8Array> {
    return new Uint8Array(await readFile(this.toAbsolute(path)));
  }

  async exists(path: string): Promise<boolean> {
    try {
      const s = await stat(this.toAbsolute(path));
      return s.isFile();
    } catch {
      return false;
    }
  }

  async listMarkdown(): Promise<string[]> {
    await this.ensureIndex();
    return this.allFiles.filter((f) => f.toLowerCase().endsWith(".md"));
  }

  async listAll(): Promise<string[]> {
    await this.ensureIndex();
    return [...this.allFiles];
  }

  private async ensureIndex(): Promise<void> {
    if (this.index) return;
    const files: string[] = [];
    const walk = async (dir: string): Promise<void> => {
      const entries = await readdir(dir, { withFileTypes: true });
      for (const entry of entries) {
        // Hidden entries and build output are never manuscript sources.
        if (entry.name.startsWith(".")) continue;
        if (entry.isDirectory()) {
          if (SKIP_DIRS.has(entry.name)) continue;
          await walk(join(dir, entry.name));
        } else if (entry.isFile()) {
          files.push(normalizePath(relative(this.root, join(dir, entry.name)).split(sep).join("/")));
        }
      }
    };
    await walk(this.root);
    files.sort();
    this.allFiles = files;

    const index = new Map<string, string[]>();
    const add = (key: string, path: string) => {
      const list = index.get(key) ?? [];
      list.push(path);
      index.set(key, list);
    };
    for (const path of files) {
      add(path.toLowerCase(), path);
      add(basename(path).toLowerCase(), path);
      add(stemOf(path).toLowerCase(), path);
      add(path.replace(/\.md$/i, "").toLowerCase(), path);
    }
    this.index = index;
  }

  async resolveLink(linkText: string, _fromPath: string): Promise<string | null> {
    await this.ensureIndex();
    const target = normalizePath(linkText.trim());
    if (!target) return null;

    const candidates =
      this.index!.get(target.toLowerCase()) ??
      this.index!.get(`${target.toLowerCase()}.md`) ??
      this.index!.get(basename(target).toLowerCase()) ??
      null;
    if (!candidates || candidates.length === 0) return null;

    // Prefer an exact path match, then a markdown file, then the shortest path —
    // which is Obsidian's "shortest path when possible" behaviour.
    const exact = candidates.find(
      (c) => c.toLowerCase() === target.toLowerCase() || c.toLowerCase() === `${target.toLowerCase()}.md`,
    );
    if (exact) return exact;
    const md = candidates.filter((c) => c.toLowerCase().endsWith(".md"));
    const pool = md.length > 0 ? md : candidates;
    return [...pool].sort((a, b) => a.length - b.length || a.localeCompare(b))[0]!;
  }
}
