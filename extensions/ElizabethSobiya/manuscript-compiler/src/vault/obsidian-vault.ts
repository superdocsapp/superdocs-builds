/**
 * VaultReader backed by Obsidian's own APIs.
 *
 * Link resolution delegates to `metadataCache.getFirstLinkpathDest`, so a link
 * resolves in the compiled book exactly the way it resolves when you click it in
 * the editor. Reimplementing Obsidian's resolution rules would guarantee drift.
 */

import type { App, TFile } from "obsidian";
import type { VaultReader } from "../core/types";
import { normalizePath } from "../core/util";

export class ObsidianVault implements VaultReader {
  constructor(private readonly app: App) {}

  private file(path: string): TFile | null {
    const f = this.app.vault.getAbstractFileByPath(normalizePath(path));
    return f && "extension" in f ? (f as TFile) : null;
  }

  async readText(path: string): Promise<string> {
    const file = this.file(path);
    if (!file) throw new Error(`Not found in the vault: ${path}`);
    // cachedRead is the right call for read-only passes: it does not warm the
    // write cache, which matters when a compile touches 300 files in a row.
    return this.app.vault.cachedRead(file);
  }

  async readBinary(path: string): Promise<Uint8Array> {
    const file = this.file(path);
    if (!file) throw new Error(`Not found in the vault: ${path}`);
    return new Uint8Array(await this.app.vault.readBinary(file));
  }

  async exists(path: string): Promise<boolean> {
    return this.file(path) !== null;
  }

  async listMarkdown(): Promise<string[]> {
    return this.app.vault.getMarkdownFiles().map((f) => f.path);
  }

  async resolveLink(linkText: string, fromPath: string): Promise<string | null> {
    const target = linkText.trim();
    if (!target) return null;
    const dest = this.app.metadataCache.getFirstLinkpathDest(target, fromPath);
    if (dest) return dest.path;
    // getFirstLinkpathDest does not resolve a path that already carries its
    // extension in every Obsidian version; fall back to a direct lookup.
    return this.file(target)?.path ?? null;
  }
}
