// Backups, and the two things about them that are easy to get wrong.
//
// A backup of an MCP config is a PLAINTEXT COPY OF A CREDENTIAL. Two
// consequences the plan calls out and this module implements:
//
//   1. It is written 0600 before any content goes into it, so the key is never
//      briefly world-readable.
//   2. Project-scoped configs (.mcp.json, .vscode/mcp.json) live inside a git
//      working tree, so the .bak lands there too and can be committed. The tool
//      says so and prints the one-line .gitignore addition.
//
// On Windows POSIX modes do not apply; the backup inherits the directory ACL
// and we say that plainly rather than implying a protection we did not apply.

import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  openSync,
  renameSync,
  statSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import { basename, dirname, join, parse, resolve } from "node:path";

export interface BackupResult {
  path: string;
  /** True when the mode was actually applied (POSIX only). */
  restricted: boolean;
  /** Set when the backup landed inside a git working tree. */
  gitWarning?: string;
}

export function backupName(target: string, now: Date): string {
  const stamp =
    now.getFullYear().toString() +
    String(now.getMonth() + 1).padStart(2, "0") +
    String(now.getDate()).padStart(2, "0") +
    "-" +
    String(now.getHours()).padStart(2, "0") +
    String(now.getMinutes()).padStart(2, "0") +
    String(now.getSeconds()).padStart(2, "0");
  return `${target}.mcp-doctor-${stamp}.bak`;
}

/** The nearest ancestor holding a .git, or null. */
export function gitRootFor(file: string): string | null {
  let dir = dirname(resolve(file));
  const { root } = parse(dir);
  while (true) {
    if (existsSync(join(dir, ".git"))) return dir;
    if (dir === root) return null;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export interface WriteBackupOptions {
  now?: Date;
  platform?: NodeJS.Platform;
}

/** Write all bytes and flush them before the caller makes the file visible. */
function writeAndSync(fd: number, contents: string): void {
  const bytes = Buffer.from(contents, "utf8");
  let offset = 0;
  while (offset < bytes.length) {
    offset += writeSync(fd, bytes, offset, bytes.length - offset);
  }
  fsyncSync(fd);
}

export function writeBackup(
  target: string,
  contents: string,
  opts: WriteBackupOptions = {},
): BackupResult {
  const now = opts.now ?? new Date();
  const platform = opts.platform ?? process.platform;
  const initial = backupName(target, now);

  // Create with the restrictive mode rather than chmod-ing afterwards: a
  // chmod leaves a window in which the credential copy is readable.
  const posix = platform !== "win32";
  let path = initial;
  let fd: number | undefined;
  for (let suffix = 0; suffix < 1000; suffix++) {
    path = suffix === 0 ? initial : initial.replace(/\.bak$/, `-${suffix}.bak`);
    try {
      fd = openSync(path, "wx", posix ? 0o600 : undefined);
      break;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== "EEXIST") throw err;
    }
  }
  if (fd === undefined) throw new Error("could not allocate a unique backup name");
  try {
    writeAndSync(fd, contents);
  } finally {
    closeSync(fd);
  }

  const result: BackupResult = { path, restricted: posix };

  const gitRoot = gitRootFor(target);
  if (gitRoot) {
    result.gitWarning =
      `${basename(path)} is a plaintext copy of your key and sits inside a git ` +
      `repository. Add this to .gitignore before committing:\n` +
      `    *.mcp-doctor-*.bak`;
  }
  if (!posix) {
    result.gitWarning =
      (result.gitWarning ? result.gitWarning + "\n" : "") +
      `File permissions were not restricted: this platform has no POSIX mode. ` +
      `The backup inherits the directory's access control.`;
  }
  return result;
}

/**
 * Replace an existing configuration atomically.
 *
 * `writeFileSync(target, text)` truncates the live config before all bytes are
 * written. A crash, full disk, or interrupted process in that window leaves a
 * broken client configuration. This writes a private sibling, fsyncs it, then
 * renames it over the target — the filesystem therefore exposes either the old
 * complete config or the new complete config, never a half-written one.
 */
export function atomicReplace(target: string, contents: string): void {
  const targetMode = statSync(target).mode & 0o777;
  const directory = dirname(target);
  const temp = join(
    directory,
    `.${basename(target)}.mcp-doctor-${process.pid}-${Date.now()}-${Math.random()
      .toString(16)
      .slice(2)}.tmp`,
  );
  let fd: number | undefined;
  try {
    // The private mode is applied *before* the credential-bearing bytes are
    // written. Preserve the original mode only immediately before the atomic
    // replacement so the repaired config's permissions do not unexpectedly
    // change.
    fd = openSync(temp, "wx", 0o600);
    writeAndSync(fd, contents);
    closeSync(fd);
    fd = undefined;
    if (process.platform !== "win32") chmodSync(temp, targetMode);
    renameSync(temp, target);
  } catch (err) {
    if (fd !== undefined) closeSync(fd);
    try {
      unlinkSync(temp);
    } catch {
      // It either was never created, or was already renamed. The original
      // error is the useful one to report to the user.
    }
    throw err;
  }
}
