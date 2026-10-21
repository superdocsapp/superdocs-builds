/**
 * The spine: one index note that defines the manuscript's order.
 *
 * Shape (everything except the chapter list is optional):
 *
 *   ---
 *   title: The Cartographer's Dilemma
 *   author: R. Alderney
 *   bibliography: References/library.bib
 *   ---
 *
 *   ## Front Matter
 *   - [[Front/Preface]]
 *
 *   ## Part One — The Survey
 *   1. [[Chapters/01 Origins]]
 *   2. [[Chapters/02 The Ledger|A Ledger in Three Hands]]
 *      - [[Chapters/02a The Marginalia]]
 *
 *   ## Back Matter
 *   - [[Back/Acknowledgements]]
 *
 * Rules, chosen so the file reads as a normal Obsidian outline:
 *   - An `## Front Matter` / `## Back Matter` heading (case-insensitive, "matter"
 *     optional) switches region. Every other `##` heading starts a body Part.
 *   - Links before any heading are body chapters with no part.
 *   - List nesting one level deep makes a sub-chapter (rendered a heading level down).
 *   - Link order in the file is the manuscript's order. Nothing else decides it.
 */

import { load as loadYaml } from "js-yaml";
import type { Diagnostic, ManuscriptMeta, SpineEntry, VaultReader } from "./types";
import { normalizePath, stemOf } from "./util";

export interface ParsedSpine {
  meta: ManuscriptMeta;
  /** Raw frontmatter, so callers can read compile options the user set on the note. */
  frontmatter: Record<string, unknown>;
  entries: SpineEntry[];
  diagnostics: Diagnostic[];
}

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

export function splitFrontmatter(src: string): { frontmatter: string | null; body: string } {
  const m = FRONTMATTER_RE.exec(src);
  if (!m) return { frontmatter: null, body: src };
  return { frontmatter: m[1]!, body: src.slice(m[0].length) };
}

function asString(v: unknown): string | undefined {
  if (v === null || v === undefined) return undefined;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (v instanceof Date) return String(v.getUTCFullYear());
  return undefined;
}

export function readMeta(fm: Record<string, unknown>, fallbackTitle: string): ManuscriptMeta {
  const keywords = Array.isArray(fm.keywords)
    ? (fm.keywords as unknown[]).map((k) => String(k))
    : typeof fm.keywords === "string"
      ? fm.keywords.split(",").map((k) => k.trim()).filter(Boolean)
      : undefined;
  return {
    title: asString(fm.title) ?? fallbackTitle,
    subtitle: asString(fm.subtitle),
    author: asString(fm.author) ?? asString(fm.authors),
    publisher: asString(fm.publisher),
    edition: asString(fm.edition),
    isbn: asString(fm.isbn),
    year: asString(fm.year),
    copyright: asString(fm.copyright),
    rights: asString(fm.rights),
    dedication: asString(fm.dedication),
    epigraph: asString(fm.epigraph),
    epigraphAttribution: asString(fm.epigraph_attribution) ?? asString(fm.epigraphAttribution),
    keywords,
  };
}

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const WIKILINK_RE = /\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]/;
const MD_LINK_RE = /\[([^\]]+)\]\(([^)]+\.md)\)/;

function regionOf(headingText: string): "front" | "body" | "back" | null {
  const t = headingText.toLowerCase().replace(/[^a-z ]/g, "").trim();
  if (/^front( matter)?$/.test(t) || t === "frontmatter") return "front";
  if (/^back( matter)?$/.test(t) || t === "backmatter" || t === "end matter") return "back";
  return null;
}

export async function parseSpine(
  vault: VaultReader,
  spinePath: string,
  src: string,
): Promise<ParsedSpine> {
  const diagnostics: Diagnostic[] = [];
  const { frontmatter, body } = splitFrontmatter(src);

  let fm: Record<string, unknown> = {};
  if (frontmatter) {
    try {
      const parsed = loadYaml(frontmatter);
      if (parsed && typeof parsed === "object") fm = parsed as Record<string, unknown>;
    } catch (err) {
      diagnostics.push({
        severity: "warning",
        code: "spine.frontmatter_invalid",
        message: `The spine's YAML frontmatter could not be parsed (${
          err instanceof Error ? err.message.split("\n")[0] : String(err)
        }). Compile continued with defaults.`,
        file: spinePath,
        line: 1,
      });
    }
  }

  const meta = readMeta(fm, stemOf(spinePath));
  const entries: SpineEntry[] = [];
  const seen = new Map<string, number>();

  let region: "front" | "body" | "back" = "body";
  let part: string | null = null;
  const lines = body.split(/\r?\n/);
  const frontmatterLines = frontmatter ? frontmatter.split(/\r?\n/).length + 2 : 0;

  let inFence = false;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]!;
    const lineNo = frontmatterLines + i + 1;

    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    const heading = HEADING_RE.exec(line);
    if (heading) {
      const text = heading[2]!.trim();
      const r = regionOf(text);
      if (r) {
        region = r;
        part = null;
      } else if (heading[1]!.length <= 2) {
        // A non-region h1/h2 opens a Part of the body.
        region = "body";
        part = text || null;
      }
      continue;
    }

    const wiki = WIKILINK_RE.exec(line);
    const md = wiki ? null : MD_LINK_RE.exec(line);
    if (!wiki && !md) continue;

    const target = wiki ? wiki[1]!.trim() : md![2]!.trim();
    const alias = wiki ? wiki[3]?.trim() : md![1]!.trim();

    const indentMatch = /^(\s*)(?:[-*+]|\d+[.)])\s/.exec(line);
    const indent = indentMatch ? indentMatch[1]!.length : 0;
    const nested = indent >= 2;

    const resolved = await vault.resolveLink(target, spinePath);
    if (!resolved) {
      diagnostics.push({
        severity: "error",
        code: "spine.broken_link",
        message: `The spine lists "${target}" but no such note exists in the vault. That chapter is missing from the compiled manuscript.`,
        file: spinePath,
        line: lineNo,
        snippet: line.trim(),
      });
      continue;
    }

    const path = normalizePath(resolved);
    if (path === normalizePath(spinePath)) {
      diagnostics.push({
        severity: "warning",
        code: "spine.self_reference",
        message: "The spine links to itself; that link was skipped.",
        file: spinePath,
        line: lineNo,
      });
      continue;
    }

    const previous = seen.get(path);
    if (previous !== undefined) {
      diagnostics.push({
        severity: "warning",
        code: "spine.duplicate_entry",
        message: `"${path}" appears on the spine more than once (first at position ${
          previous + 1
        }). The repeat was skipped, because the same note twice would duplicate every anchor in it.`,
        file: spinePath,
        line: lineNo,
      });
      continue;
    }
    seen.set(path, entries.length);

    entries.push({
      path,
      title: alias || stemOf(path),
      region,
      part: region === "body" ? part : null,
      order: entries.length,
      level: nested ? 2 : 1,
      nested,
    });
  }

  if (entries.length === 0) {
    diagnostics.push({
      severity: "error",
      code: "spine.empty",
      message: `No chapter links were found in "${spinePath}". A spine is a note whose body lists its chapters as [[wikilinks]] in order.`,
      file: spinePath,
    });
  }

  return { meta, frontmatter: fm, entries, diagnostics };
}
