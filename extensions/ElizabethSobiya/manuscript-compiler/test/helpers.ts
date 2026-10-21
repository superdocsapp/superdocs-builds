/**
 * Test helpers: an in-memory vault and a scripted SuperDocs transport.
 *
 * Neither touches the disk or the network, so the whole suite runs on a fresh
 * clone with no API key and no cost. That is a requirement, not a convenience:
 * a test suite that needs a paid key is a test suite nobody runs.
 */

import type { VaultReader } from "../src/core/types";
import type { HttpRequest, HttpResponse, Transport } from "../src/superdocs/client";

export class MemoryVault implements VaultReader {
  readonly files: Map<string, string>;
  readonly binaries = new Map<string, Uint8Array>();
  /** Every path read, in order — lets a test assert what was *not* touched. */
  readonly reads: string[] = [];

  constructor(files: Record<string, string> = {}) {
    this.files = new Map(Object.entries(files));
  }

  set(path: string, content: string): void {
    this.files.set(path, content);
  }

  setBinary(path: string, bytes: Uint8Array): void {
    this.binaries.set(path, bytes);
  }

  delete(path: string): void {
    this.files.delete(path);
  }

  async readText(path: string): Promise<string> {
    this.reads.push(path);
    const content = this.files.get(path);
    if (content === undefined) throw new Error(`Not found: ${path}`);
    return content;
  }

  async readBinary(path: string): Promise<Uint8Array> {
    const bytes = this.binaries.get(path);
    if (!bytes) throw new Error(`Not found: ${path}`);
    return bytes;
  }

  async exists(path: string): Promise<boolean> {
    return this.files.has(path) || this.binaries.has(path);
  }

  async listMarkdown(): Promise<string[]> {
    return [...this.files.keys()].filter((p) => p.endsWith(".md"));
  }

  async resolveLink(linkText: string, _fromPath: string): Promise<string | null> {
    const target = linkText.trim();
    const all = [...this.files.keys(), ...this.binaries.keys()];
    if (all.includes(target)) return target;
    if (all.includes(`${target}.md`)) return `${target}.md`;
    const base = target.split("/").pop()!;
    const byName = all.filter((p) => p.endsWith(`/${base}`) || p === base);
    if (byName.length > 0) return byName.sort((a, b) => a.length - b.length)[0]!;
    const byStem = all.filter((p) => p.replace(/\.md$/, "").endsWith(`/${base}`));
    return byStem.sort((a, b) => a.length - b.length)[0] ?? null;
  }
}

export interface ScriptedCall {
  /** Matched against the request URL as a substring. */
  match: string;
  method?: HttpRequest["method"];
  status?: number;
  /** JSON body, or raw bytes for an export. */
  json?: unknown;
  bytes?: Uint8Array;
  headers?: Record<string, string>;
}

export interface FakeServer {
  transport: Transport;
  /** Every request the client made, for assertions. */
  requests: Array<{ method: string; url: string; body: unknown }>;
}

/**
 * A transport that replies from a script.
 *
 * Entries are consumed in order when they match; an unmatched request fails the
 * test loudly rather than returning a plausible empty object, because a fake that
 * silently succeeds is how mock-only tests end up proving nothing.
 */
export function fakeServer(script: ScriptedCall[]): FakeServer {
  const remaining = [...script];
  const requests: FakeServer["requests"] = [];

  const transport: Transport = async (req) => {
    let parsedBody: unknown = req.body;
    if (typeof req.body === "string") {
      try {
        parsedBody = JSON.parse(req.body);
      } catch {
        parsedBody = req.body;
      }
    }
    requests.push({ method: req.method, url: req.url, body: parsedBody });

    const index = remaining.findIndex(
      (s) => req.url.includes(s.match) && (!s.method || s.method === req.method),
    );
    if (index < 0) {
      throw new Error(
        `The test script has no reply for ${req.method} ${req.url}. Remaining: ${remaining
          .map((s) => s.match)
          .join(", ") || "(none)"}`,
      );
    }
    const entry = remaining.splice(index, 1)[0]!;
    const text = entry.bytes ? "" : JSON.stringify(entry.json ?? {});
    const buffer = entry.bytes
      ? entry.bytes.buffer.slice(
          entry.bytes.byteOffset,
          entry.bytes.byteOffset + entry.bytes.byteLength,
        )
      : new TextEncoder().encode(text).buffer;
    return {
      status: entry.status ?? 200,
      headers: entry.headers ?? { "content-type": entry.bytes ? "application/pdf" : "application/json" },
      text,
      arrayBuffer: buffer as ArrayBuffer,
    } satisfies HttpResponse;
  };

  return { transport, requests };
}

export const noSleep = async (): Promise<void> => undefined;
