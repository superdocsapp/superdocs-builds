/**
 * A small, dependency-free BibTeX reader.
 *
 * Scope is deliberate: it parses the entry shapes a working author's `.bib` file
 * actually contains — `@book`, `@article`, `@incollection`, `@misc`, brace- and
 * quote-delimited values, `@string` macros, `#` concatenation, comments, and the
 * common LaTeX accents/escapes. It does NOT try to be a LaTeX engine.
 *
 * Anything it cannot parse becomes a diagnostic, never a silent drop. A citation
 * that resolves to nothing must be visible in the output and in the report.
 */

import type { Diagnostic } from "./types";

export interface BibEntry {
  key: string;
  type: string;
  fields: Record<string, string>;
  /** Parsed author list, "Last, First" order preserved per author. */
  authors: BibAuthor[];
  year: string | null;
  title: string;
  /** 1-based line in the .bib file where the entry starts. */
  line: number;
}

export interface BibAuthor {
  last: string;
  first: string;
  /** "others" from `and others` -> renders as "et al." */
  isOthers: boolean;
}

export interface BibDatabase {
  entries: Map<string, BibEntry>;
  diagnostics: Diagnostic[];
}

const LATEX_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\\&/g, "&"],
  [/\\%/g, "%"],
  [/\\\$/g, "$"],
  [/\\_/g, "_"],
  [/\\#/g, "#"],
  [/\\ldots\b/g, "…"],
  [/---/g, "—"],
  [/--/g, "–"],
  [/``/g, "“"],
  [/''/g, "”"],
  [/\\'\{?([a-zA-Z])\}?/g, "$1\u0301"],
  [/\\`\{?([a-zA-Z])\}?/g, "$1\u0300"],
  [/\\"\{?([a-zA-Z])\}?/g, "$1\u0308"],
  [/\\\^\{?([a-zA-Z])\}?/g, "$1\u0302"],
  [/\\~\{?([a-zA-Z])\}?/g, "$1\u0303"],
  [/\\c\{?([a-zA-Z])\}?/g, "$1\u0327"],
  [/\\ss\b/g, "ß"],
  [/\\o\b/g, "ø"],
  [/\\aa\b/g, "å"],
];

function cleanValue(raw: string): string {
  let s = raw;
  for (const [re, rep] of LATEX_REPLACEMENTS) s = s.replace(re, rep);
  // Braces in BibTeX protect capitalisation; they carry no meaning once parsed.
  s = s.replace(/[{}]/g, "");
  s = s.replace(/\s+/g, " ").trim();
  return s.normalize("NFC");
}

export function parseAuthors(raw: string): BibAuthor[] {
  if (!raw.trim()) return [];
  return raw
    .split(/\s+and\s+/i)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      if (chunk.toLowerCase() === "others") {
        return { last: "others", first: "", isOthers: true };
      }
      if (chunk.includes(",")) {
        const [last, ...rest] = chunk.split(",");
        return { last: last!.trim(), first: rest.join(",").trim(), isOthers: false };
      }
      const parts = chunk.split(/\s+/);
      if (parts.length === 1) return { last: parts[0]!, first: "", isOthers: false };
      const last = parts.pop()!;
      return { last, first: parts.join(" "), isOthers: false };
    });
}

/**
 * Read a value starting at `i`, which points at `{`, `"`, or the first char of a
 * bare token. Returns the raw text and the index just past the value.
 */
function readValue(src: string, i: number): { value: string; next: number } | null {
  const ch = src[i];
  if (ch === "{") {
    let depth = 0;
    let j = i;
    for (; j < src.length; j += 1) {
      const c = src[j];
      if (c === "\\") {
        j += 1;
        continue;
      }
      if (c === "{") depth += 1;
      else if (c === "}") {
        depth -= 1;
        if (depth === 0) return { value: src.slice(i + 1, j), next: j + 1 };
      }
    }
    return null; // unbalanced
  }
  if (ch === '"') {
    let depth = 0;
    let j = i + 1;
    for (; j < src.length; j += 1) {
      const c = src[j];
      if (c === "\\") {
        j += 1;
        continue;
      }
      if (c === "{") depth += 1;
      else if (c === "}") depth -= 1;
      else if (c === '"' && depth === 0) return { value: src.slice(i + 1, j), next: j + 1 };
    }
    return null;
  }
  const m = /^[^\s,}]+/.exec(src.slice(i));
  if (!m) return null;
  return { value: m[0], next: i + m[0].length };
}

function lineAt(src: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index && i < src.length; i += 1) if (src[i] === "\n") line += 1;
  return line;
}

export function parseBibtex(src: string, file: string): BibDatabase {
  const entries = new Map<string, BibEntry>();
  const diagnostics: Diagnostic[] = [];
  const strings = new Map<string, string>();

  let i = 0;
  while (i < src.length) {
    const at = src.indexOf("@", i);
    if (at < 0) break;

    const typeMatch = /^@([a-zA-Z]+)\s*[{(]/.exec(src.slice(at));
    if (!typeMatch) {
      i = at + 1;
      continue;
    }
    const type = typeMatch[1]!.toLowerCase();
    const entryStart = at;
    let j = at + typeMatch[0].length;

    if (type === "comment") {
      const v = readValue(src, j - 1);
      i = v ? v.next : j;
      continue;
    }

    if (type === "preamble") {
      const v = readValue(src, j - 1);
      i = v ? v.next : j;
      continue;
    }

    if (type === "string") {
      const nameMatch = /^\s*([^\s=]+)\s*=\s*/.exec(src.slice(j));
      if (nameMatch) {
        const vStart = j + nameMatch[0].length;
        const v = readValue(src, vStart);
        if (v) {
          strings.set(nameMatch[1]!.toLowerCase(), cleanValue(v.value));
          const close = src.indexOf("}", v.next);
          i = close < 0 ? v.next : close + 1;
          continue;
        }
      }
      i = j;
      continue;
    }

    // Entry key runs to the first comma.
    const keyMatch = /^\s*([^,\s}]+)\s*,?/.exec(src.slice(j));
    if (!keyMatch) {
      diagnostics.push({
        severity: "warning",
        code: "bibtex.malformed_entry",
        message: `Could not read the citation key of an @${type} entry; the entry was skipped.`,
        file,
        line: lineAt(src, entryStart),
      });
      i = j;
      continue;
    }
    const key = keyMatch[1]!;
    j += keyMatch[0].length;

    const fields: Record<string, string> = {};
    let closed = false;
    while (j < src.length) {
      // Skip whitespace and stray commas.
      while (j < src.length && /[\s,]/.test(src[j]!)) j += 1;
      if (src[j] === "}" || src[j] === ")") {
        j += 1;
        closed = true;
        break;
      }
      const fieldMatch = /^([a-zA-Z][a-zA-Z0-9_:-]*)\s*=\s*/.exec(src.slice(j));
      if (!fieldMatch) break;
      j += fieldMatch[0].length;
      const parts: string[] = [];
      for (;;) {
        const v = readValue(src, j);
        if (!v) break;
        const bare = v.value;
        const isBare = src[j] !== "{" && src[j] !== '"';
        parts.push(isBare && strings.has(bare.toLowerCase()) ? strings.get(bare.toLowerCase())! : bare);
        j = v.next;
        while (j < src.length && /\s/.test(src[j]!)) j += 1;
        if (src[j] === "#") {
          j += 1;
          while (j < src.length && /\s/.test(src[j]!)) j += 1;
          continue;
        }
        break;
      }
      fields[fieldMatch[1]!.toLowerCase()] = cleanValue(parts.join(""));
    }

    if (!closed) {
      diagnostics.push({
        severity: "warning",
        code: "bibtex.unterminated_entry",
        message: `Entry "${key}" is not closed with a brace; it was parsed as far as possible.`,
        file,
        line: lineAt(src, entryStart),
      });
    }

    if (entries.has(key)) {
      diagnostics.push({
        severity: "warning",
        code: "bibtex.duplicate_key",
        message: `Citation key "${key}" is defined more than once. The first definition wins.`,
        file,
        line: lineAt(src, entryStart),
      });
    } else {
      const yearRaw = fields.year ?? fields.date ?? "";
      const year = /(\d{4})/.exec(yearRaw)?.[1] ?? null;
      entries.set(key, {
        key,
        type,
        fields,
        authors: parseAuthors(fields.author ?? fields.editor ?? ""),
        year,
        title: fields.title ?? "",
        line: lineAt(src, entryStart),
      });
    }

    i = j;
  }

  return { entries, diagnostics };
}
