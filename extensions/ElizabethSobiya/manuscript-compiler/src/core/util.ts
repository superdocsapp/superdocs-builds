import { sha256Hex } from "./sha256";

/** Deterministic sha256, hex, truncated to 16 chars — plenty for cache keys. */
export function hash(input: string | Uint8Array): string {
  return sha256Hex(input).slice(0, 16);
}

/** Full-length sha256 for content-addressed image uploads. */
export function hashFull(input: Uint8Array): string {
  return sha256Hex(input);
}

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]!);
}

export function escapeAttr(s: string): string {
  return escapeHtml(s);
}

/** Strip tags and collapse whitespace — used for word counts and ToC text. */
export function stripTags(html: string): string {
  return html
    .replace(/<\/(p|div|li|h[1-6]|tr|td|th|figcaption|blockquote)>/gi, " ")
    .replace(/<[^>]*>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function wordCount(html: string): number {
  const text = stripTags(html);
  if (!text) return 0;
  return text.split(/\s+/).length;
}

/**
 * URL-safe, stable, collision-resistant anchor slug.
 * Stability matters: anchors end up as Word bookmarks and ToC hyperlinks, and a
 * slug that drifts between compiles would silently break every cross-reference.
 */
export function slugify(input: string): string {
  const base = input
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return base || "x";
}

/** Make a slug unique against a set, appending -2, -3, ... deterministically. */
export function uniqueSlug(base: string, taken: Set<string>): string {
  if (!taken.has(base)) {
    taken.add(base);
    return base;
  }
  let n = 2;
  while (taken.has(`${base}-${n}`)) n += 1;
  const out = `${base}-${n}`;
  taken.add(out);
  return out;
}

/** POSIX-normalise a vault path and drop any leading "./". */
export function normalizePath(p: string): string {
  return p.replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/{2,}/g, "/");
}

export function basename(p: string): string {
  const n = normalizePath(p);
  return n.slice(n.lastIndexOf("/") + 1);
}

export function stemOf(p: string): string {
  const b = basename(p);
  const dot = b.lastIndexOf(".");
  return dot > 0 ? b.slice(0, dot) : b;
}

export function extOf(p: string): string {
  const b = basename(p);
  const dot = b.lastIndexOf(".");
  return dot > 0 ? b.slice(dot + 1).toLowerCase() : "";
}

export function dirOf(p: string): string {
  const n = normalizePath(p);
  const slash = n.lastIndexOf("/");
  return slash < 0 ? "" : n.slice(0, slash);
}

/** Join vault-relative path segments. */
export function joinPath(...parts: string[]): string {
  return normalizePath(parts.filter(Boolean).join("/"));
}

/** Format ms with one decimal place, for the timing report. */
export function ms(n: number): string {
  return `${n.toFixed(1)}ms`;
}
