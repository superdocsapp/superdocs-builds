/**
 * The compile orchestrator: vault in, one assembled manuscript out.
 *
 * Stages are explicit and timed, because "where did the 40 seconds go" is a
 * question a 300-page compile will eventually make someone ask.
 *
 * Nothing here touches the network. Compiling is free, offline and repeatable;
 * SuperDocs is involved only when you export the result or ask for an editorial
 * pass. That separation is deliberate — it means the expensive, rate-limited part
 * of the system is never on the path of an ordinary save-and-recompile.
 */

import { parseBibtex, type BibDatabase } from "./bibtex";
import {
  buildManifest,
  diffAgainstManifest,
  loadManifest,
  planReuse,
  type Manifest,
} from "./cache";
import {
  PAGE_BREAK,
  bibliographySection,
  copyrightPage,
  dedicationPage,
  epigraphPage,
  listOfFigures,
  notesSection,
  partTitlePage,
  tableOfContents,
  titlePage,
} from "./matter";
import {
  assignNumbers,
  renderEndnoteSection,
  renderFootnoteParts,
  type AssignedFigure,
} from "./numbering";
import { renderChapter } from "./render";
import { scanForInjection } from "./injection";
import { parseSpine } from "./spine";
import { sanitizeSource } from "./tokens";
import type {
  CompileOptions,
  CompileResult,
  Diagnostic,
  HeadingRef,
  RenderedChapter,
  SpineEntry,
  StageTiming,
  VaultReader,
} from "./types";
import { hash, normalizePath, slugify, wordCount } from "./util";

export interface CompileInput {
  vault: VaultReader;
  options: CompileOptions;
  /** Previous manifest JSON, or null for a cold compile. */
  manifestJson: string | null;
  onProgress?: (stage: string, detail?: string) => void;
  signal?: { aborted: boolean };
}

export interface CompileOutput extends CompileResult {
  manifest: Manifest;
  /** Figures with their assigned labels, for the image upload step. */
  assignedFigures: AssignedFigure[];
  /** Chapters that were re-rendered this run rather than reused from cache. */
  reRendered: string[];
}

class Aborted extends Error {
  constructor() {
    super("Compile aborted");
    this.name = "Aborted";
  }
}

/** Stable per-note anchor. Derived from the path, so it survives reordering. */
export function anchorForPath(path: string): string {
  const withoutExt = normalizePath(path).replace(/\.md$/i, "");
  return `ch-${slugify(withoutExt)}`;
}

/** Options that change rendered bytes. Assembly-only options are excluded on purpose. */
function renderOptionsHash(options: CompileOptions): string {
  return hash(JSON.stringify({ spine: options.spinePath }));
}

function entrySalt(entry: SpineEntry): string {
  return JSON.stringify({
    level: entry.level,
    region: entry.region,
    title: entry.title,
  });
}

async function readIfPossible(vault: VaultReader, path: string): Promise<string | null> {
  try {
    return await vault.readText(path);
  } catch {
    return null;
  }
}

export async function compile(input: CompileInput): Promise<CompileOutput> {
  const { vault, options } = input;
  const timings: StageTiming[] = [];
  const diagnostics: Diagnostic[] = [];
  // A compile treats its source snapshot as immutable. Cache the promise rather
  // than only the resolved text so concurrent hash jobs deduplicate the same
  // shared transclusion instead of racing identical filesystem reads.
  const sourceCache = new Map<string, Promise<string | null>>();
  const readSource = (path: string): Promise<string | null> => {
    const key = normalizePath(path);
    let pending = sourceCache.get(key);
    if (!pending) {
      pending = readIfPossible(vault, key).then((src) =>
        src === null ? null : sanitizeSource(src),
      );
      sourceCache.set(key, pending);
    }
    return pending;
  };
  const progress = input.onProgress ?? (() => {});
  const checkAbort = () => {
    if (input.signal?.aborted) throw new Aborted();
  };

  const time = async <T>(stage: string, fn: () => Promise<T> | T): Promise<T> => {
    // Every stage boundary is a cancellation point. Without this the only place a
    // compile could be interrupted was the render loop, which is not where a cold
    // compile spends its time — on a cold cache `hash-sources` dominates, and a
    // user who has asked to stop should not wait out the slowest stage.
    checkAbort();
    const t0 = performance.now();
    try {
      return await fn();
    } finally {
      timings.push({ stage, ms: performance.now() - t0 });
    }
  };

  const manifest = loadManifest(input.manifestJson);

  // --- 1. Spine -------------------------------------------------------------
  progress("spine", options.spinePath);
  const spineSrc = await time("read-spine", async () => {
    const src = await readSource(options.spinePath);
    if (src === null) {
      throw new Error(
        `Spine note not found: "${options.spinePath}". Point the setting at the index note that lists your chapters.`,
      );
    }
    return src;
  });

  const parsed = await time("parse-spine", () => parseSpine(vault, options.spinePath, spineSrc));
  diagnostics.push(...parsed.diagnostics);
  const spine = parsed.entries;

  // The spine's own frontmatter may override compile options, so a manuscript
  // travels with its settings rather than depending on one machine's preferences.
  const effective = applyFrontmatterOptions(options, parsed.frontmatter, diagnostics);

  // --- 2. Bibliography ------------------------------------------------------
  let bib: BibDatabase | null = null;
  if (effective.bibliographyPath) {
    await time("bibliography", async () => {
      const resolved =
        (await vault.exists(effective.bibliographyPath!))
          ? effective.bibliographyPath!
          : await vault.resolveLink(effective.bibliographyPath!, effective.spinePath);
      if (!resolved) {
        diagnostics.push({
          severity: "error",
          code: "bibliography.missing",
          message: `The bibliography "${effective.bibliographyPath}" was not found in the vault. Citations cannot be resolved, and each one will print as an unresolved marker.`,
          file: effective.spinePath,
        });
        return;
      }
      const src = await readIfPossible(vault, resolved);
      if (src === null) {
        diagnostics.push({
          severity: "error",
          code: "bibliography.unreadable",
          message: `The bibliography "${resolved}" could not be read.`,
          file: resolved,
        });
        return;
      }
      bib = parseBibtex(src, resolved);
      diagnostics.push(...bib.diagnostics);
    });
  }

  // --- 3. Reuse plan --------------------------------------------------------
  const optionsHash = renderOptionsHash(effective);
  const spineIndex = new Map(spine.map((e) => [e.path, e]));

  const currentHashes = await time("hash-sources", async () => {
    const map = new Map<string, string>();
    await Promise.all(
      spine.map(async (entry) => {
        checkAbort();
        const recorded = manifest.chapters[entry.path];
        const deps = recorded?.dependencies?.length ? recorded.dependencies : [entry.path];
        const texts: string[] = [];
        for (const dep of deps) {
          const text = await readSource(dep);
          if (text === null) return; // a vanished dependency forces a re-render
          texts.push(text);
        }
        map.set(entry.path, hash(texts.join("\u0000") + "\u0000" + entrySalt(entry)));
      }),
    );
    return map;
  });

  const plan = planReuse(
    manifest,
    optionsHash,
    currentHashes,
    spine.map((e) => e.path),
  );

  // --- 4. Render ------------------------------------------------------------
  const takenAnchors = new Set<string>();
  const reRendered: string[] = [];
  const reRenderedSet = new Set<string>();
  const chapters: RenderedChapter[] = [];

  await time("render", async () => {
    for (const entry of spine) {
      checkAbort();
      const cached = plan.reusable.has(entry.path) ? manifest.chapters[entry.path] : undefined;
      if (cached && manifest.renders[entry.path] !== undefined) {
        progress("reuse", entry.path);
        chapters.push({
          entry,
          html: manifest.renders[entry.path]!,
          sourceHash: cached.sourceHash,
          renderHash: cached.renderHash,
          figures: [],
          footnotes: [],
          citations: [],
          headings: [],
          diagnostics: [],
          dependencies: cached.dependencies,
        });
        continue;
      }
      progress("render", entry.path);
      reRendered.push(entry.path);
      reRenderedSet.add(entry.path);
      const rendered = await renderChapter({
        vault,
        entry,
        spineIndex,
        anchorForPath,
        takenAnchors,
        renderSalt: entrySalt(entry),
        readSource: async (path) => {
          const src = await readSource(path);
          if (src === null) throw new Error(`Source note not found: "${path}".`);
          return src;
        },
      });
      chapters.push(rendered);
      diagnostics.push(...rendered.diagnostics);
    }
  });

  // A reused chapter has no in-memory figure/footnote/heading lists — they were
  // never re-derived. Recover them from the cached HTML so numbering, the ToC and
  // the list of figures stay complete without re-rendering markdown.
  await time("rehydrate", () => {
    for (const ch of chapters) {
      if (!reRenderedSet.has(ch.entry.path)) {
        rehydrateFromCache(ch, manifest, takenAnchors);
      }
    }
  });

  // --- 5. Injection scan ----------------------------------------------------
  await time("injection-scan", async () => {
    for (const entry of spine) {
      checkAbort();
      const src = await readSource(entry.path);
      if (src !== null) diagnostics.push(...scanForInjection(src, entry.path));
    }
  });

  // --- 6. Numbering ---------------------------------------------------------
  const numbering = await time("numbering", () =>
    assignNumbers(chapters, {
      figureNumbering: effective.figureNumbering,
      citationStyle: effective.citationStyle,
      bib,
    }),
  );
  diagnostics.push(...numbering.diagnostics);

  // --- 7. Assemble ----------------------------------------------------------
  const assembled = await time("assemble", () =>
    assembleDocument({
      options: effective,
      meta: parsed.meta,
      spine,
      resolvedChapters: numbering.chapters,
      headings: chapters.flatMap((c) => c.headings),
      figures: numbering.figures,
      footnotes: numbering.footnotes,
      citationOrder: numbering.citationOrder,
      bib,
    }),
  );

  // --- 8. Diff and manifest --------------------------------------------------
  const resolvedHashes = new Map<string, string>();
  numbering.chapters.forEach((html, i) => {
    resolvedHashes.set(chapters[i]!.entry.path, hash(html));
  });

  const changes = diffAgainstManifest(manifest, chapters, resolvedHashes, plan.reasons);
  const outputHash = hash(assembled.html);
  const nextManifest = buildManifest(
    manifest,
    optionsHash,
    hash(spineSrc),
    chapters,
    resolvedHashes,
    outputHash,
  );

  if (bib) reportUncitedEntries(bib, numbering.citationOrder, diagnostics, effective);

  const words = numbering.chapters.reduce((n, html) => n + wordCount(html), 0);
  const errors = diagnostics.filter((d) => d.severity === "error").length;
  const strictErrors = effective.strict
    ? diagnostics.filter((d) => d.severity === "warning").length
    : 0;

  return {
    html: assembled.html,
    meta: parsed.meta,
    spine,
    diagnostics,
    changes,
    stats: {
      chapters: spine.length,
      words,
      figures: numbering.figures.length,
      footnotes: numbering.footnotes.length,
      citations: numbering.citationOrder.length,
      uniqueSources: new Set(chapters.flatMap((c) => c.dependencies)).size,
      estimatedPages: Math.max(1, Math.ceil(words / 300)),
      bytes: assembled.html.length,
    },
    timings,
    ok: errors === 0 && strictErrors === 0,
    manifest: nextManifest,
    assignedFigures: numbering.figures,
    reRendered,
  };
}

/** Compile options a manuscript can carry in its spine's frontmatter. */
function applyFrontmatterOptions(
  options: CompileOptions,
  fm: Record<string, unknown>,
  diagnostics: Diagnostic[],
): CompileOptions {
  const out: CompileOptions = { ...options };
  const bibliography = fm.bibliography ?? fm.bib;
  if (typeof bibliography === "string" && bibliography.trim()) {
    out.bibliographyPath = normalizePath(bibliography.trim());
  }
  const style = fm.citation_style ?? fm.citationStyle;
  if (style === "numeric" || style === "author-date") out.citationStyle = style;
  else if (style !== undefined) {
    diagnostics.push({
      severity: "warning",
      code: "spine.unknown_citation_style",
      message: `Unknown citation_style "${String(style)}" in the spine. Using "${out.citationStyle}". Valid values: author-date, numeric.`,
      file: options.spinePath,
    });
  }
  const figNum = fm.figure_numbering ?? fm.figureNumbering;
  if (figNum === "continuous" || figNum === "by-chapter") out.figureNumbering = figNum;
  const fnPlacement = fm.footnotes ?? fm.footnote_placement;
  if (fnPlacement === "footnote" || fnPlacement === "endnote") out.footnotePlacement = fnPlacement;
  if (typeof fm.toc_depth === "number") out.tocDepth = Math.max(0, Math.min(6, fm.toc_depth));
  if (typeof fm.page_break_per_chapter === "boolean") {
    out.pageBreakPerChapter = fm.page_break_per_chapter;
  }
  return out;
}

/**
 * Restore a reused chapter's structural metadata from the manifest.
 *
 * A reused chapter is never re-parsed, so its figures, footnote bodies, citation
 * occurrences and headings come back from the checkpoint rather than from the
 * cached HTML. Re-deriving them by regex over the cached markup was the first
 * design here, and it silently dropped footnote bodies — those are assembled
 * outside the chapter's own markup, so they were simply not there to find.
 */
function rehydrateFromCache(
  ch: RenderedChapter,
  manifest: Manifest,
  takenAnchors: Set<string>,
): void {
  const recorded = manifest.chapters[ch.entry.path];
  if (!recorded) return;
  ch.figures = recorded.figures ?? [];
  ch.footnotes = recorded.footnotes ?? [];
  ch.citations = recorded.citations ?? [];
  ch.headings = recorded.headings ?? [];
  for (const h of ch.headings) takenAnchors.add(h.anchor);
}

interface AssembleInput {
  options: CompileOptions;
  meta: CompileResult["meta"];
  spine: SpineEntry[];
  resolvedChapters: string[];
  headings: HeadingRef[];
  figures: AssignedFigure[];
  footnotes: ReturnType<typeof assignNumbers>["footnotes"];
  citationOrder: string[];
  bib: BibDatabase | null;
}

function assembleDocument(input: AssembleInput): { html: string } {
  const { options, meta, spine, resolvedChapters, figures, footnotes, bib } = input;
  const parts: string[] = [];
  const push = (html: string) => {
    if (html.trim()) parts.push(html);
  };
  const breakPage = () => {
    if (options.pageBreakPerChapter) parts.push(PAGE_BREAK);
  };

  if (options.titlePage) {
    push(titlePage(meta));
    breakPage();
  }
  if (options.copyrightPage) {
    push(copyrightPage(meta));
    breakPage();
  }
  const dedication = dedicationPage(meta);
  if (dedication) {
    push(dedication);
    breakPage();
  }
  const epigraph = epigraphPage(meta);
  if (epigraph) {
    push(epigraph);
    breakPage();
  }

  const toc = tableOfContents(input.headings, options.tocDepth);
  if (toc) {
    push(toc);
    breakPage();
  }
  if (options.listOfFigures) {
    const lof = listOfFigures(figures);
    if (lof) {
      push(lof);
      breakPage();
    }
  }

  let currentPart: string | null = null;
  spine.forEach((entry, i) => {
    const html = resolvedChapters[i] ?? "";
    if (entry.region === "body" && entry.part && entry.part !== currentPart) {
      currentPart = entry.part;
      push(partTitlePage(entry.part));
      breakPage();
    }
    if (entry.region !== "body") currentPart = null;
    push(html);
    if (i < spine.length - 1) breakPage();
  });

  if (options.footnotePlacement === "endnote") {
    const titles = new Map(spine.map((e) => [e.order, e.title]));
    const notes = notesSection(renderEndnoteSection(footnotes, titles));
    if (notes) {
      breakPage();
      push(notes);
    }
  }

  if (options.bibliographySection && bib) {
    const biblio = bibliographySection(bib, input.citationOrder, options.citationStyle);
    if (biblio) {
      breakPage();
      push(biblio);
    }
  }

  // Out-of-flow footnote parts go last: SuperDocs lifts them out of the body flow
  // into real Word footnotes, so their position in the HTML is bookkeeping only.
  if (options.footnotePlacement === "footnote") {
    const asides = renderFootnoteParts(footnotes);
    if (asides) parts.push(asides);
  }

  return { html: parts.join("\n") };
}

function reportUncitedEntries(
  bib: BibDatabase,
  cited: string[],
  diagnostics: Diagnostic[],
  options: CompileOptions,
): void {
  const citedSet = new Set(cited);
  const unused = [...bib.entries.keys()].filter((k) => !citedSet.has(k));
  if (unused.length === 0) return;
  diagnostics.push({
    severity: "info",
    code: "bibliography.uncited_entries",
    message: `${unused.length} bibliography ${
      unused.length === 1 ? "entry is" : "entries are"
    } never cited, so ${
      unused.length === 1 ? "it is" : "they are"
    } not printed in the reference list: ${unused.slice(0, 8).join(", ")}${
      unused.length > 8 ? ", …" : ""
    }`,
    file: options.bibliographyPath ?? undefined,
  });
}
