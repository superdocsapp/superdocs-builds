// Parsing a config into a value PLUS the source spans of every node.
//
// Spans are collected now, in the read-only step, even though nothing writes
// yet. That is deliberate: the span-edit model (PLAN D6) only works if the
// parser can point at the exact bytes of a value, and discovering in step 3
// that a parser cannot do that would mean rewriting the parsing layer under a
// finished diagnosis layer.

import { parseTree, type Node } from "jsonc-parser";
import { parse as parseToml } from "smol-toml";

export interface Span {
  offset: number;
  length: number;
}

export interface ParsedNode {
  value: unknown;
  /** Span of the VALUE — not the key, and not the whole key/value pair. */
  span: Span;
  children?: Map<string, ParsedNode>;
}

export interface DuplicateKey {
  /** Dotted path to the object holding the repeat, e.g. `mcpServers.superdocs`. */
  container: string;
  key: string;
}

export interface ParseSuccess {
  ok: true;
  root: ParsedNode;
  /** A UTF-8 BOM, kept so it can be written back untouched. */
  bom: boolean;
  /** Repeated keys. JSON says the last wins, which quietly hides the first —
   *  so a wrong URL can sit above a right one and never be seen. */
  duplicates: DuplicateKey[];
}

export interface ParseFailure {
  ok: false;
  reason: string;
  line?: number;
  column?: number;
  empty?: boolean;
}

export type ParseResult = ParseSuccess | ParseFailure;

const BOM = "﻿";

function offsetToLineCol(text: string, offset: number): { line: number; column: number } {
  let line = 1;
  let last = -1;
  for (let i = 0; i < offset && i < text.length; i++) {
    if (text[i] === "\n") {
      line++;
      last = i;
    }
  }
  return { line, column: offset - last };
}

// ── JSON / JSONC ─────────────────────────────────────────────────────────
//
// Both go through jsonc-parser. Plain JSON could use JSON.parse, but then the
// two formats would take different code paths and only one would carry spans.
// One path, one behaviour.

function convert(node: Node, path: string, duplicates: DuplicateKey[]): ParsedNode {
  const span: Span = { offset: node.offset, length: node.length };

  if (node.type === "object") {
    const children = new Map<string, ParsedNode>();
    for (const prop of node.children ?? []) {
      const [keyNode, valueNode] = prop.children ?? [];
      if (!keyNode || !valueNode) continue;
      const key = String(keyNode.value);
      // Later keys win, matching JSON.parse — but the shadowed one is recorded
      // rather than forgotten, so a stale value hiding above a good one is
      // visible instead of silent.
      if (children.has(key)) duplicates.push({ container: path || "(root)", key });
      children.set(key, convert(valueNode, path ? `${path}.${key}` : key, duplicates));
    }
    const value: Record<string, unknown> = {};
    for (const [k, v] of children) value[k] = v.value;
    return { value, span, children };
  }

  if (node.type === "array") {
    const items = (node.children ?? []).map((c, i) =>
      convert(c, `${path}[${i}]`, duplicates),
    );
    return { value: items.map((i) => i.value), span };
  }

  return { value: node.value, span };
}

export function parseJsonLike(text: string, allowJsonc = true): ParseResult {
  const bom = text.startsWith(BOM);
  const body = bom ? text.slice(BOM.length) : text;

  if (body.trim() === "") return { ok: false, reason: "file is empty", empty: true };

  const errors: { error: number; offset: number; length: number }[] = [];
  const tree = parseTree(body, errors, {
    allowTrailingComma: allowJsonc,
    disallowComments: !allowJsonc,
  });

  if (errors.length > 0 || !tree) {
    const first = errors[0];
    const offset = (first?.offset ?? 0) + (bom ? BOM.length : 0);
    const { line, column } = offsetToLineCol(text, offset);
    return { ok: false, reason: "invalid JSON", line, column };
  }

  const duplicates: DuplicateKey[] = [];
  const root = convert(tree, "", duplicates);
  if (bom) shiftSpans(root, BOM.length);
  return { ok: true, root, bom, duplicates };
}

function shiftSpans(node: ParsedNode, by: number): void {
  node.span.offset += by;
  for (const child of node.children?.values() ?? []) shiftSpans(child, by);
}

// ── TOML ─────────────────────────────────────────────────────────────────
//
// smol-toml validates and gives a value but no spans, so spans are recovered by
// locating the target text. Adequate for the read-only step; step 3 must prove
// the located span is the right one before any TOML repair is allowed to run,
// which is why codex ships with repairs disabled.

export function parseTomlText(text: string): ParseResult {
  const bom = text.startsWith(BOM);
  const body = bom ? text.slice(BOM.length) : text;

  if (body.trim() === "") return { ok: false, reason: "file is empty", empty: true };

  try {
    const value = parseToml(body) as Record<string, unknown>;
    return {
      ok: true,
      bom,
      // TOML forbids duplicate keys outright: the parser rejects them, so a
      // successful parse means there are none to report.
      duplicates: [],
      root: { value, span: { offset: bom ? BOM.length : 0, length: body.length } },
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const match = /line (\d+)/i.exec(message);
    // smol-toml's human rendering uses a decorative caret whose offset is not
    // the source column.  One common, unambiguous malformed shape is an
    // unfinished table header; report the real end-of-line position so this
    // implementation agrees with Python's tomllib and gives the developer a
    // useful location.  Other parser errors retain a safe line-only fallback.
    const unfinishedHeader = body
      .split(/\r?\n/)
      .findIndex((line) => /^\s*\[[^\]]*$/.test(line));
    const headerLine = unfinishedHeader >= 0 ? body.split(/\r?\n/)[unfinishedHeader]! : undefined;
    return {
      ok: false,
      reason: "invalid TOML",
      line: headerLine ? unfinishedHeader + 1 : match ? Number(match[1]) : undefined,
      column: headerLine ? headerLine.length + 1 : undefined,
    };
  }
}

export function parseByFormat(text: string, format: "json" | "jsonc" | "toml"): ParseResult {
  return format === "toml" ? parseTomlText(text) : parseJsonLike(text, format === "jsonc");
}
