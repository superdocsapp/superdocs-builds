/**
 * Citation parsing and rendering.
 *
 * Syntax (a practical subset of Pandoc's, which is what writers already know):
 *   [@smith2019]                -> (Smith 2019)
 *   [@smith2019, p. 42]         -> (Smith 2019, p. 42)
 *   [-@smith2019]               -> (2019)                 author suppressed
 *   [@smith2019; @jones2020]    -> (Smith 2019; Jones 2020)
 *   @smith2019                  -> Smith (2019)           narrative form
 *
 * Numeric style renders [1], [1, p. 42], [1; 2] with numbers assigned in order of
 * first appearance across the whole manuscript — which is exactly why citations
 * are emitted as tokens and resolved at assembly, not at chapter render time.
 *
 * An unresolved key is never silently dropped. It renders as a visible marker and
 * raises a diagnostic. The compiler must not invent a source.
 */

import type { BibDatabase, BibEntry } from "./bibtex";
import type { CitationRef, CitationStyle } from "./types";
import { escapeHtml } from "./util";

export interface ParsedCitation {
  refs: CitationRef[];
  /** Raw matched text, for diagnostics. */
  raw: string;
}

const KEY_RE = "[A-Za-z][A-Za-z0-9_:.#$%&+?<>~/-]*";

/** Bracketed group: [@a, p. 1; -@b] */
const BRACKET_RE = new RegExp(`\\[(-?@${KEY_RE}(?:[^\\]]*))\\]`, "g");
/** Narrative form: @key not preceded by [ or a word character or an email-ish char. */
const NARRATIVE_RE = new RegExp(`(^|[^\\[\\w@./-])@(${KEY_RE})`, "g");

function parseBracketBody(body: string): CitationRef[] {
  const refs: CitationRef[] = [];
  for (const part of body.split(";")) {
    const m = new RegExp(`^\\s*(-?)@(${KEY_RE})\\s*(?:,\\s*(.*))?$`).exec(part);
    if (!m) continue;
    refs.push({
      citeKey: m[2]!,
      locator: m[3]?.trim() ? m[3]!.trim() : null,
      suppressAuthor: m[1] === "-",
      narrative: false,
    });
  }
  return refs;
}

/** Names for an author-date citation: "Smith", "Smith and Jones", "Smith et al." */
export function formatAuthorNames(entry: BibEntry): string {
  const authors = entry.authors.filter((a) => !a.isOthers);
  const hasOthers = entry.authors.some((a) => a.isOthers);
  if (authors.length === 0) {
    return entry.fields.organization ?? entry.fields.publisher ?? entry.title ?? entry.key;
  }
  if (hasOthers || authors.length > 3) return `${authors[0]!.last} et al.`;
  if (authors.length === 1) return authors[0]!.last;
  if (authors.length === 2) return `${authors[0]!.last} and ${authors[1]!.last}`;
  return `${authors[0]!.last}, ${authors[1]!.last} and ${authors[2]!.last}`;
}

export interface CitationRenderContext {
  style: CitationStyle;
  bib: BibDatabase | null;
  /** Assigns/returns the 1-based number for a key in numeric style. */
  numberFor: (key: string) => number;
  /** Anchor of the bibliography entry, for hyperlinking. */
  anchorFor: (key: string) => string | null;
}

/** Render one bracketed citation group (or a narrative citation) to final HTML. */
export function renderCitationGroup(refs: CitationRef[], ctx: CitationRenderContext): string {
  if (refs.length === 0) return "";

  const rendered = refs.map((ref) => {
    const entry = ctx.bib?.entries.get(ref.citeKey) ?? null;
    if (!entry) {
      // Never bluff: an unresolved key stays visible in the manuscript.
      return `<span class="citation citation-unresolved" data-cite-key="${escapeHtml(
        ref.citeKey,
      )}" title="No bibliography entry for this key">[?&nbsp;${escapeHtml(ref.citeKey)}]</span>`;
    }
    const anchor = ctx.anchorFor(ref.citeKey);
    const inner =
      ctx.style === "numeric"
        ? String(ctx.numberFor(ref.citeKey))
        : ref.suppressAuthor
          ? entry.year ?? "n.d."
          : `${formatAuthorNames(entry)} ${entry.year ?? "n.d."}`;
    const withLocator = ref.locator ? `${inner}, ${escapeHtml(ref.locator)}` : inner;
    const body = escapeCitationInner(withLocator);
    return anchor
      ? `<a class="citation" href="#${anchor}" data-cite-key="${escapeHtml(ref.citeKey)}">${body}</a>`
      : `<span class="citation" data-cite-key="${escapeHtml(ref.citeKey)}">${body}</span>`;
  });

  if (refs.length === 1 && refs[0]!.narrative) {
    const ref = refs[0]!;
    const entry = ctx.bib?.entries.get(ref.citeKey);
    if (entry) {
      const anchor = ctx.anchorFor(ref.citeKey);
      const label =
        ctx.style === "numeric"
          ? `[${ctx.numberFor(ref.citeKey)}]`
          : `(${escapeHtml(entry.year ?? "n.d.")})`;
      const name = escapeHtml(formatAuthorNames(entry));
      const linked = anchor ? `<a class="citation" href="#${anchor}">${label}</a>` : label;
      return `${name}&nbsp;${linked}`;
    }
    return rendered[0]!;
  }

  const joined = rendered.join("; ");
  return ctx.style === "numeric" ? `[${joined}]` : `(${joined})`;
}

/** The inner text is already escaped piecewise; this guards the join. */
function escapeCitationInner(s: string): string {
  return s.replace(/&(?!(amp|lt|gt|quot|#39|nbsp);)/g, "&amp;");
}

/**
 * Find every citation in a markdown source and hand each occurrence to `emit`,
 * which returns the replacement text (a token, during chapter render).
 */
export function replaceCitations(
  src: string,
  emit: (refs: CitationRef[], raw: string) => string,
): string {
  let out = src.replace(BRACKET_RE, (raw, body: string) => {
    const refs = parseBracketBody(body);
    return refs.length ? emit(refs, raw) : raw;
  });
  out = out.replace(NARRATIVE_RE, (_raw, lead: string, key: string) => {
    return (
      lead +
      emit([{ citeKey: key, locator: null, suppressAuthor: false, narrative: true }], `@${key}`)
    );
  });
  return out;
}

/**
 * Sort key for the bibliography: author surname, then year, then title.
 *
 * It sorts by the name the reader actually sees, so a corporate author files under
 * its own name rather than under its title — an entry printed as "National Survey
 * Office" filed under "R" for "Revision Policy" is the kind of small wrongness a
 * copy-editor circles.
 */
export function bibSortKey(entry: BibEntry): string {
  const first = entry.authors.find((a) => !a.isOthers);
  const name =
    first?.last ?? entry.fields.organization ?? entry.fields.publisher ?? entry.title ?? entry.key;
  return `${name.toLowerCase()}|${entry.year ?? "9999"}|${entry.title.toLowerCase()}`;
}

/** Render a bibliography entry as a formatted reference line. */
export function renderBibEntry(entry: BibEntry, style: CitationStyle, number: number): string {
  const f = entry.fields;
  const parts: string[] = [];

  const authorList = entry.authors.length
    ? entry.authors
        .map((a) => (a.isOthers ? "et al." : a.first ? `${a.last}, ${a.first}` : a.last))
        .join("; ")
    : (f.organization ?? "");
  if (authorList) parts.push(escapeHtml(authorList));
  if (entry.year) parts.push(`(${escapeHtml(entry.year)})`);
  if (entry.title) parts.push(`<em>${escapeHtml(entry.title)}</em>`);

  if (entry.type === "article" && f.journal) {
    const vol = f.volume ? ` ${escapeHtml(f.volume)}` : "";
    const num = f.number ? `(${escapeHtml(f.number)})` : "";
    const pages = f.pages ? `: ${escapeHtml(f.pages)}` : "";
    parts.push(`${escapeHtml(f.journal)}${vol}${num}${pages}`);
  } else if (f.booktitle) {
    parts.push(`In ${escapeHtml(f.booktitle)}`);
  }
  if (f.publisher) parts.push(escapeHtml(f.publisher));
  if (f.address) parts.push(escapeHtml(f.address));
  if (f.doi) parts.push(`doi:${escapeHtml(f.doi)}`);
  else if (f.url) parts.push(escapeHtml(f.url));

  // Join with full stops, but never double one up: "et al." already ends a sentence.
  const body = parts.reduce((acc, part) => {
    if (!acc) return part;
    return /[.!?]$/.test(acc) ? `${acc} ${part}` : `${acc}. ${part}`;
  }, "");
  const terminated = /[.!?]$/.test(body) ? body : `${body}.`;
  const marker = style === "numeric" ? `<span class="bib-number">[${number}]</span> ` : "";
  return `${marker}${terminated}`;
}
