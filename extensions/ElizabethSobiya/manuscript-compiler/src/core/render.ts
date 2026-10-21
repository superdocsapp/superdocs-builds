/**
 * Chapter rendering: one note in, one tokenised HTML fragment out.
 *
 * The output deliberately contains no manuscript-wide numbers. Figures, footnotes
 * and citations become tokens (see tokens.ts) that the assembly pass resolves.
 * That is what lets an unchanged chapter keep a byte-identical cached render even
 * when a chapter before it gains a figure.
 *
 * Obsidian syntax handled here:
 *   ![[Figures/map.png|Caption text]]   place a figure with a caption
 *   [[Figures/map.png]]                 cross-reference -> "Figure 3.1"
 *   ![[Shared/Boilerplate]]             transclude another note (depth-limited)
 *   [[Chapters/02 Ledger]]              cross-reference to another chapter
 *   [[#A Heading]] / [[Note#Heading]]   cross-reference to a heading
 *   ^[an inline note]                   footnote, converted from the inline form
 *   [^id] ... [^id]: body               footnote, reference form
 *   [@key, p. 3] / @key                 citation resolved from the bibliography
 *   > [!note] Title                     callout
 */

import MarkdownIt from "markdown-it";
import type {
  CitationRef,
  Diagnostic,
  FigureRef,
  FootnoteRef,
  HeadingRef,
  RenderedChapter,
  SpineEntry,
  VaultReader,
} from "./types";
import { token, sanitizeSource } from "./tokens";
import { replaceCitations } from "./citations";
import { splitFrontmatter } from "./spine";
import { escapeAttr, escapeHtml, extOf, hash, slugify, stemOf, stripTags } from "./util";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif"]);
const MAX_EMBED_DEPTH = 3;

export interface RenderContext {
  vault: VaultReader;
  /** Sanitized, per-compile source reader. Falls back to the vault for direct use. */
  readSource?: (path: string) => Promise<string>;
  entry: SpineEntry;
  /** Vault paths of every note on the spine, for cross-reference resolution. */
  spineIndex: Map<string, SpineEntry>;
  /** Anchor for a spine note, e.g. "ch-02-the-ledger". */
  anchorForPath: (path: string) => string;
  /** Anchors already used across the manuscript, to keep every id unique. */
  takenAnchors: Set<string>;
  /** Options that affect rendered bytes; folded into the cache key. */
  renderSalt: string;
}

interface Protected {
  text: string;
  restore: (html: string) => string;
}

const PROTECT_OPEN = "\uE010";
const PROTECT_CLOSE = "\uE011";

/** Footnote-body capsules: `<open>key<sep>body<close>`, lifted out before rendering. */
const CAPSULE_OPEN = "\uE012";
const CAPSULE_SEP = "\uE013";
const CAPSULE_CLOSE = "\uE014";
const CAPSULE_RE = new RegExp(
  `${CAPSULE_OPEN}([^${CAPSULE_SEP}]*)${CAPSULE_SEP}([\\s\\S]*?)${CAPSULE_CLOSE}`,
  "g",
);

/** Hide fenced/inline code from every other transform, then put it back verbatim. */
function protectCode(src: string): Protected {
  const store: string[] = [];
  const keep = (s: string) => {
    store.push(s);
    return `${PROTECT_OPEN}${store.length - 1}${PROTECT_CLOSE}`;
  };
  let out = src.replace(/^(```|~~~)[^\n]*\n[\s\S]*?^\1[^\n]*$/gm, (m) => keep(m));
  out = out.replace(/(`+)([^`\n]|[^`\n][\s\S]*?[^`\n])\1(?!`)/g, (m) => keep(m));
  return {
    text: out,
    restore: (html: string) =>
      html.replace(
        new RegExp(`${PROTECT_OPEN}(\\d+)${PROTECT_CLOSE}`, "g"),
        (_m, i: string) => store[Number(i)] ?? "",
      ),
  };
}

/** Pull `[^id]: body` definitions out of the source; returns the stripped source. */
function extractFootnoteDefs(src: string): { body: string; defs: Map<string, string> } {
  const defs = new Map<string, string>();
  const lines = src.split("\n");
  const kept: string[] = [];
  for (let i = 0; i < lines.length; i += 1) {
    const m = /^\[\^([^\]]+)\]:\s?(.*)$/.exec(lines[i]!);
    if (!m) {
      kept.push(lines[i]!);
      continue;
    }
    const parts = [m[2]!];
    // Continuation lines are indented by at least four spaces or a tab.
    while (i + 1 < lines.length && /^(\s{4,}|\t)/.test(lines[i + 1]!)) {
      i += 1;
      parts.push(lines[i]!.replace(/^(\s{4}|\t)/, ""));
    }
    defs.set(m[1]!, parts.join("\n").trim());
  }
  return { body: kept.join("\n"), defs };
}

function headingLevelMap(src: string): Map<number, number> {
  const seen = new Set<number>();
  for (const line of src.split("\n")) {
    const m = /^(#{1,6})\s+\S/.exec(line);
    if (m) seen.add(m[1]!.length);
  }
  return new Map([...seen].sort((a, b) => a - b).map((lvl, i) => [lvl, i]));
}

/**
 * Normalise heading levels.
 *
 * Distinct levels used in the note are mapped onto consecutive levels starting one
 * below the chapter's own level. A note that uses `#`/`###` and a note that uses
 * `##`/`###` come out identical, and no level is ever skipped — which is what makes
 * a generated table of contents and Word's navigation pane behave.
 */
export function normaliseHeadings(src: string, chapterLevel: number): string {
  const map = headingLevelMap(src);
  if (map.size === 0) return src;
  const base = Math.min(chapterLevel + 1, 6);
  return src
    .split("\n")
    .map((line) => {
      const m = /^(#{1,6})(\s+)(.*)$/.exec(line);
      if (!m || !m[3]!.trim()) return line;
      const depth = map.get(m[1]!.length) ?? 0;
      const level = Math.min(base + depth, 6);
      return `${"#".repeat(level)}${m[2]}${m[3]}`;
    })
    .join("\n");
}

function createMarkdownIt(): MarkdownIt {
  const md = new MarkdownIt({
    html: true,
    xhtmlOut: false,
    breaks: false,
    linkify: false,
    typographer: true,
    quotes: "“”‘’",
  });
  // Manuscripts are print objects: a bare newline is not a line break, and smart
  // punctuation is wanted. Everything else is CommonMark, deliberately.
  return md;
}

const md = createMarkdownIt();


export async function renderChapter(ctx: RenderContext): Promise<RenderedChapter> {
  const { entry, vault } = ctx;
  const diagnostics: Diagnostic[] = [];
  const figures: FigureRef[] = [];
  const footnotes: FootnoteRef[] = [];
  const citations: CitationRef[] = [];
  const headings: HeadingRef[] = [];
  const dependencies: string[] = [entry.path];

  const raw = ctx.readSource
    ? await ctx.readSource(entry.path)
    : sanitizeSource(await vault.readText(entry.path));
  const sourceTexts: string[] = [raw];

  const { body: afterFm } = splitFrontmatter(raw);
  const expanded = await expandEmbeds(afterFm, ctx, 0, dependencies, sourceTexts, diagnostics);

  const { body: noDefs, defs } = extractFootnoteDefs(expanded);
  const protectedCode = protectCode(noDefs);
  let text = protectedCode.text;

  // Chapter title: the spine alias wins; otherwise the note's first h1.
  let title = entry.title;
  const firstH1 = /^#\s+(.+)$/m.exec(text);
  if (firstH1 && text.slice(0, firstH1.index).trim() === "") {
    if (!entry.title || entry.title === stemOf(entry.path)) title = firstH1[1]!.trim();
    text = text.slice(0, firstH1.index) + text.slice(firstH1.index + firstH1[0].length);
  }

  // Every id the chapter emits is keyed off its stable anchor rather than its
  // position on the spine. Moving a chapter therefore renumbers the book without
  // rewriting a single chapter's bytes.
  const chapterKey = ctx.anchorForPath(entry.path);
  const usedFootnoteIds = new Set<string>();
  let inlineCounter = 0;

  // --- Footnotes -------------------------------------------------------------
  //
  // Markers are substituted here, but each note's BODY is left inline in the text
  // stream inside a capsule, and only lifted out after cross-references and
  // citations have run. That ordering is the whole point: a footnote is where
  // scholarly citations actually live, and an earlier version of this pipeline
  // pulled the bodies out first — so every [@key] inside a footnote silently
  // failed to resolve and the reference was dropped from the bibliography.
  // Keeping the bodies inline until after the citation pass also means citation
  // numbering follows true reading order, marker by marker.

  const capsules = new Map<string, string>();

  const capsule = (key: string, body: string): string =>
    `${CAPSULE_OPEN}${key}${CAPSULE_SEP}${body}${CAPSULE_CLOSE}`;

  function footnoteMarker(key: string): string {
    return `<sup data-footnote-ref="fn-${escapeAttr(footnoteId(key))}" role="doc-noteref">${token(
      "fn",
      key,
    )}</sup>`;
  }

  // Inline form first: ^[note text]
  text = text.replace(/\^\[((?:[^\[\]]|\[[^\]]*\])*)\]/g, (_m, bodyText: string) => {
    inlineCounter += 1;
    const key = `${chapterKey}:i${inlineCounter}`;
    capsules.set(key, bodyText.trim());
    return footnoteMarker(key) + capsule(key, bodyText.trim());
  });

  // Reference form: [^id]
  text = text.replace(/\[\^([^\]]+)\]/g, (m, id: string) => {
    const def = defs.get(id);
    if (def === undefined) {
      diagnostics.push({
        severity: "error",
        code: "footnote.undefined",
        message: `Footnote [^${id}] is referenced but never defined in this note. No note text was invented for it.`,
        file: entry.path,
        snippet: m,
      });
      return `<span class="mc-missing-footnote">[?&nbsp;footnote ${escapeHtml(id)}]</span>`;
    }
    usedFootnoteIds.add(id);
    const key = `${chapterKey}:${id}`;
    if (capsules.has(key)) {
      // A second reference to the same note reuses the first note's number.
      return footnoteMarker(key);
    }
    capsules.set(key, def);
    return footnoteMarker(key) + capsule(key, def);
  });

  for (const id of defs.keys()) {
    if (!usedFootnoteIds.has(id)) {
      diagnostics.push({
        severity: "warning",
        code: "footnote.orphan",
        message: `Footnote [^${id}] is defined but never referenced, so it does not appear in the manuscript.`,
        file: entry.path,
      });
    }
  }

  // --- Figures and transclusion-free embeds --------------------------------
  text = await replaceAsync(text, /!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g, async (m, target, cap) => {
    const t = (target ?? "").trim();
    if (!IMAGE_EXTS.has(extOf(t))) return m; // handled by expandEmbeds already
    return renderFigure(t, cap ?? "", m);
  });

  text = await replaceAsync(
    text,
    /!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g,
    async (m, alt, src) => {
      const target = (src ?? "").trim();
      if (!target) return m;
      if (/^https?:/i.test(target)) return renderFigure(target, alt ?? "", m, true);
      if (!IMAGE_EXTS.has(extOf(target))) return m;
      return renderFigure(decodeURIComponent(target), alt ?? "", m);
    },
  );

  async function renderFigure(
    target: string,
    caption: string,
    matched: string,
    isRemote = false,
  ): Promise<string> {
    const resolved = isRemote ? target : await vault.resolveLink(target, entry.path);
    if (!resolved && !isRemote) {
      diagnostics.push({
        severity: "error",
        code: "figure.missing_file",
        message: `"${target}" is placed as a figure but that file is not in the vault. The figure is missing from the compiled manuscript.`,
        file: entry.path,
        snippet: matched.slice(0, 120),
      });
      return `<p class="mc-missing-figure">[missing figure: ${escapeHtml(target)}]</p>`;
    }
    const path = resolved ?? target;
    const key = figureKey(path);
    if (figures.some((f) => f.key === key)) {
      diagnostics.push({
        severity: "warning",
        code: "figure.duplicate_placement",
        message: `"${path}" is placed twice in this chapter. Cross-references to it will point at the first placement.`,
        file: entry.path,
      });
    }
    const captionText = caption.trim();
    if (!captionText) {
      diagnostics.push({
        severity: "warning",
        code: "figure.no_caption",
        message: `The figure "${path}" has no caption. Print figures read badly without one; add it as ![[${target}|Your caption]].`,
        file: entry.path,
      });
    }
    figures.push({
      key,
      sourcePath: isRemote ? null : path,
      caption: escapeHtml(captionText),
      altText: escapeHtml(captionText || stemOf(path)),
      chapterOrder: entry.order,
    });
    const label = token("fig", key);
    // "Figure 1.1 — Caption." The separator is part of the caption, not the label,
    // so the List of Figures can reuse the label on its own.
    const captionHtml = captionText
      ? `<figcaption><span class="figure-label">${label}</span> &#8212; ${escapeHtml(
          captionText,
        )}</figcaption>`
      : `<figcaption><span class="figure-label">${label}</span></figcaption>`;
    return (
      `\n\n<figure id="fig-${escapeAttr(key)}" data-figure-key="${escapeAttr(key)}" ` +
      `data-figure-src="${escapeAttr(path)}">` +
      `<img src="${escapeAttr(isRemote ? target : path)}" alt="${escapeAttr(
        captionText || stemOf(path),
      )}">${captionHtml}</figure>\n\n`
    );
  }

  // --- Cross-references ------------------------------------------------------
  text = await replaceAsync(
    text,
    /(?<!!)\[\[([^\]|#]*)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]/g,
    async (m, target, frag, alias) => {
      const t = (target ?? "").trim();
      const fragment = frag?.trim() ?? "";
      const label = alias?.trim() ?? "";

      // [[Figures/map.png]] -> "Figure 3.1"
      if (t && IMAGE_EXTS.has(extOf(t))) {
        const resolved = await vault.resolveLink(t, entry.path);
        const key = figureKey(resolved ?? t);
        return `<a class="xref xref-figure" href="#fig-${escapeAttr(key)}">${token(
          "figref",
          key,
        )}</a>`;
      }

      // [[#Heading]] — same chapter.
      if (!t && fragment) {
        const anchor = headingAnchor(entry, fragment, ctx);
        return `<a class="xref xref-section" href="#${escapeAttr(anchor)}">${escapeHtml(
          label || fragment,
        )}</a>`;
      }

      const resolved = t ? await vault.resolveLink(t, entry.path) : entry.path;
      if (!resolved) {
        diagnostics.push({
          severity: "warning",
          code: "link.broken",
          message: `"${t}" is linked from this chapter but no such note exists. It was compiled as plain text.`,
          file: entry.path,
          snippet: m,
        });
        return escapeHtml(label || t);
      }
      const targetEntry = ctx.spineIndex.get(resolved);
      if (!targetEntry) {
        // A link to a note that is not part of the book: keep the words, drop the link.
        diagnostics.push({
          severity: "info",
          code: "link.off_spine",
          message: `"${resolved}" is linked from this chapter but is not on the spine, so there is nothing in the manuscript to link to. The text was kept, the link was dropped.`,
          file: entry.path,
        });
        return escapeHtml(label || stemOf(resolved));
      }
      const anchor = fragment
        ? headingAnchor(targetEntry, fragment, ctx)
        : ctx.anchorForPath(resolved);
      return `<a class="xref xref-chapter" href="#${escapeAttr(anchor)}">${escapeHtml(
        label || targetEntry.title,
      )}</a>`;
    },
  );

  // --- Citations -------------------------------------------------------------
  text = replaceCitations(text, (refs) => {
    citations.push(...refs);
    return token(
      "cite",
      refs
        .map(
          (r) =>
            `${r.suppressAuthor ? "-" : ""}${r.narrative ? ">" : ""}${r.citeKey}${
              r.locator ? `|${r.locator}` : ""
            }`,
        )
        .join("~"),
    );
  });

  // --- Lift footnote bodies back out ------------------------------------------
  // Everything inside a capsule has now been through the same figure,
  // cross-reference and citation passes as body text.
  text = text.replace(CAPSULE_RE, (_m, key: string, body: string) => {
    const trimmed = body.trim();
    const isBlock = /\n\s*\n/.test(trimmed) || /^(#{1,6}\s|[-*+]\s|\d+[.)]\s|>)/.test(trimmed);
    footnotes.push({
      key,
      html: isBlock ? md.render(trimmed).trim() : `<p>${md.renderInline(trimmed)}</p>`,
      chapterOrder: entry.order,
    });
    return "";
  });

  // --- Callouts --------------------------------------------------------------
  text = transformCallouts(text);

  // --- Headings --------------------------------------------------------------
  text = normaliseHeadings(text, entry.level);

  let html = md.render(text);
  html = protectedCode.restore(html);
  html = anchorHeadings(html, entry, ctx, headings, diagnostics);

  const chapterAnchor = ctx.anchorForPath(entry.path);
  const titleTag = `h${Math.min(entry.level, 6)}`;
  const heading =
    `<${titleTag} id="${escapeAttr(chapterAnchor)}" class="chapter-title" ` +
    `data-chapter-path="${escapeAttr(entry.path)}">${escapeHtml(title)}</${titleTag}>`;
  headings.unshift({
    level: entry.level,
    text: title,
    anchor: chapterAnchor,
    chapterOrder: entry.order,
  });

  const section =
    `<section class="chapter chapter-${entry.region}" ` +
    `data-chapter-path="${escapeAttr(entry.path)}">\n${heading}\n${html.trim()}\n</section>`;

  const sourceHash = hash(sourceTexts.join("\u0000") + "\u0000" + ctx.renderSalt);
  return {
    entry: { ...entry, title },
    html: section,
    sourceHash,
    renderHash: hash(section),
    figures,
    footnotes,
    citations,
    headings,
    diagnostics,
    dependencies,
  };
}

function figureKey(path: string): string {
  return slugify(stemOf(path));
}

export function footnoteId(key: string): string {
  return key.replace(/[^A-Za-z0-9]+/g, "-");
}

function headingAnchor(entry: SpineEntry, headingText: string, ctx: RenderContext): string {
  return `${ctx.anchorForPath(entry.path)}--${slugify(headingText)}`;
}

/** Add stable ids to rendered headings and collect them for the ToC. */
function anchorHeadings(
  html: string,
  entry: SpineEntry,
  ctx: RenderContext,
  out: HeadingRef[],
  diagnostics: Diagnostic[],
): string {
  return html.replace(
    /<h([1-6])>([\s\S]*?)<\/h\1>/g,
    (_m, level: string, inner: string) => {
      const text = stripTags(inner);
      let anchor = headingAnchor(entry, text, ctx);
      if (ctx.takenAnchors.has(anchor)) {
        // Two identical headings in one chapter would otherwise emit duplicate ids,
        // which breaks Word bookmarks and makes [[#Heading]] ambiguous. Say so.
        diagnostics.push({
          severity: "warning",
          code: "heading.duplicate",
          message: `The heading "${text}" appears more than once here. Cross-references written as [[#${text}]] resolve to the first one.`,
          file: entry.path,
        });
        let n = 2;
        while (ctx.takenAnchors.has(`${anchor}-${n}`)) n += 1;
        anchor = `${anchor}-${n}`;
      }
      ctx.takenAnchors.add(anchor);
      out.push({ level: Number(level), text, anchor, chapterOrder: entry.order });
      return `<h${level} id="${escapeAttr(anchor)}">${inner}</h${level}>`;
    },
  );
}

const CALLOUT_TYPES = new Set([
  "note",
  "info",
  "tip",
  "warning",
  "caution",
  "danger",
  "quote",
  "example",
  "abstract",
  "summary",
]);

/** `> [!note] Title` blocks become semantic blockquotes that survive to DOCX. */
export function transformCallouts(src: string): string {
  return src
    .split("\n")
    .map((line) => {
      const m = /^(\s*>+\s*)\[!([a-zA-Z]+)\][+-]?\s*(.*)$/.exec(line);
      if (!m) return line;
      const type = m[2]!.toLowerCase();
      const cls = CALLOUT_TYPES.has(type) ? type : "note";
      const title = m[3]!.trim() || cls.charAt(0).toUpperCase() + cls.slice(1);
      return `${m[1]}<strong class="callout-title callout-${cls}">${escapeHtml(title)}</strong>`;
    })
    .join("\n");
}

/**
 * Expand `![[Some Note]]` transclusions.
 *
 * Notes that are themselves on the spine are never transcluded — they are chapters,
 * and inlining one would duplicate every anchor inside it. Everything else (shared
 * boilerplate, a rights statement, a recurring sidebar) is pulled in, recursively,
 * to a fixed depth. Each pulled-in file joins the chapter's cache dependencies, so
 * editing the boilerplate re-renders exactly the chapters that use it.
 */
async function expandEmbeds(
  src: string,
  ctx: RenderContext,
  depth: number,
  dependencies: string[],
  sourceTexts: string[],
  diagnostics: Diagnostic[],
): Promise<string> {
  if (depth >= MAX_EMBED_DEPTH) return src;
  let changed = false;
  const out = await replaceAsync(src, /!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g, async (m, target) => {
    const t = (target ?? "").trim();
    if (IMAGE_EXTS.has(extOf(t))) return m;
    const resolved = await ctx.vault.resolveLink(t, ctx.entry.path);
    if (!resolved) {
      diagnostics.push({
        severity: "warning",
        code: "embed.missing_note",
        message: `"${t}" is embedded here but no such note exists. The embed was left as literal text.`,
        file: ctx.entry.path,
        snippet: m,
      });
      return m;
    }
    if (ctx.spineIndex.has(resolved)) {
      diagnostics.push({
        severity: "warning",
        code: "embed.spine_note",
        message: `"${resolved}" is embedded here but it is already a chapter on the spine. The embed was skipped to avoid printing it twice.`,
        file: ctx.entry.path,
      });
      return "";
    }
    changed = true;
    if (!dependencies.includes(resolved)) dependencies.push(resolved);
    const text = ctx.readSource
      ? await ctx.readSource(resolved)
      : sanitizeSource(await ctx.vault.readText(resolved));
    sourceTexts.push(text);
    return splitFrontmatter(text).body.trim();
  });
  return changed
    ? expandEmbeds(out, ctx, depth + 1, dependencies, sourceTexts, diagnostics)
    : out;
}

/** String.replace with an async replacer. Matches are resolved left to right. */
export async function replaceAsync(
  src: string,
  re: RegExp,
  fn: (match: string, ...groups: (string | undefined)[]) => Promise<string> | string,
): Promise<string> {
  const matches: RegExpExecArray[] = [];
  const rx = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  let m: RegExpExecArray | null;
  while ((m = rx.exec(src)) !== null) {
    matches.push(m);
    if (m[0] === "") rx.lastIndex += 1;
  }
  if (matches.length === 0) return src;
  const replacements = await Promise.all(
    matches.map((mm) => fn(mm[0]!, ...(mm.slice(1) as (string | undefined)[]))),
  );
  let out = "";
  let last = 0;
  matches.forEach((mm, i) => {
    out += src.slice(last, mm.index) + replacements[i];
    last = mm.index + mm[0]!.length;
  });
  return out + src.slice(last);
}
