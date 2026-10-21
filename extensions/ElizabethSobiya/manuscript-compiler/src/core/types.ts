/**
 * Shared types for the manuscript compiler core.
 *
 * Everything in `src/core` is pure: it never imports Obsidian, never touches the
 * network, and never reads the filesystem directly. It talks to the outside world
 * through the `VaultReader` interface below, which the Obsidian plugin and the
 * headless CLI each implement. That is what makes the whole compiler unit-testable
 * without a vault, without Obsidian, and without an API key.
 */

/** Minimal read-only view of a vault. Implemented by Obsidian and by node:fs. */
export interface VaultReader {
  /** Read a UTF-8 text file. Path is vault-relative, POSIX separators. */
  readText(path: string): Promise<string>;
  /** Read a binary file (figures). */
  readBinary(path: string): Promise<Uint8Array>;
  /** True if the path exists as a file. */
  exists(path: string): Promise<boolean>;
  /**
   * Resolve a wikilink target ("Chapters/01 Origins", "01 Origins", "fig.png")
   * to a concrete vault path, mimicking Obsidian's shortest-unique-path linking.
   * Returns null when the link is broken.
   */
  resolveLink(linkText: string, fromPath: string): Promise<string | null>;
  /** All markdown file paths in the vault (used for link resolution + diagnostics). */
  listMarkdown(): Promise<string[]>;
}

export type Severity = "error" | "warning" | "info";

export interface Diagnostic {
  severity: Severity;
  /** Stable machine code, e.g. "citation.unresolved". */
  code: string;
  message: string;
  /** Vault path the problem lives in, when known. */
  file?: string;
  /** 1-based line number inside `file`, when known. */
  line?: number;
  /** The offending token, verbatim. */
  snippet?: string;
}

/** One entry on the manuscript spine. */
export interface SpineEntry {
  /** Vault path of the source note. */
  path: string;
  /** Display title (from the spine link alias, the note's h1, or the filename). */
  title: string;
  /** Which structural region the entry belongs to. */
  region: "front" | "body" | "back";
  /** Part grouping inside the body, e.g. "Part One: The Survey". Null when ungrouped. */
  part: string | null;
  /** Index within the spine, 0-based, in document order. */
  order: number;
  /** Heading level the entry's own title is rendered at (1 for chapters, 2 for sub-notes). */
  level: number;
  /** True when the entry came from a nested (indented) spine bullet. */
  nested: boolean;
}

export interface ManuscriptMeta {
  title: string;
  subtitle?: string;
  author?: string;
  /** Free-form fields surfaced to the front-matter templates. */
  publisher?: string;
  edition?: string;
  isbn?: string;
  year?: string;
  copyright?: string;
  rights?: string;
  dedication?: string;
  epigraph?: string;
  epigraphAttribution?: string;
  keywords?: string[];
}

export type CitationStyle = "author-date" | "numeric";
export type FigureNumbering = "continuous" | "by-chapter";
export type FootnotePlacement = "footnote" | "endnote";

export interface CompileOptions {
  /** Vault path of the spine (index) note. */
  spinePath: string;
  /** Vault path of the BibTeX bibliography. Empty disables citation resolution. */
  bibliographyPath: string | null;
  citationStyle: CitationStyle;
  figureNumbering: FigureNumbering;
  footnotePlacement: FootnotePlacement;
  /** Heading depth included in the table of contents (1-6). 0 disables the ToC. */
  tocDepth: number;
  /** Insert a page break before every body chapter. */
  pageBreakPerChapter: boolean;
  /** Generate a title page from the spine metadata. */
  titlePage: boolean;
  /** Generate a copyright page. */
  copyrightPage: boolean;
  /** Generate a "List of Figures" after the ToC. */
  listOfFigures: boolean;
  /** Emit the resolved bibliography as a back-matter section. */
  bibliographySection: boolean;
  /** Treat unresolved citations / missing figures as errors rather than warnings. */
  strict: boolean;
}

export const DEFAULT_COMPILE_OPTIONS: CompileOptions = {
  spinePath: "Manuscript.md",
  bibliographyPath: null,
  citationStyle: "author-date",
  figureNumbering: "by-chapter",
  footnotePlacement: "footnote",
  tocDepth: 2,
  pageBreakPerChapter: true,
  titlePage: true,
  copyrightPage: true,
  listOfFigures: true,
  bibliographySection: true,
  strict: false,
};

/** A figure discovered while rendering a chapter, before global numbering. */
export interface FigureRef {
  /** Stable key used by cross-references: the slug of the image path. */
  key: string;
  /** Vault path of the image, or null when the link is broken. */
  sourcePath: string | null;
  /** Caption text (already HTML-escaped). */
  caption: string;
  altText: string;
  /** Chapter this figure belongs to (spine order). */
  chapterOrder: number;
}

/** A footnote discovered while rendering a chapter, before global numbering. */
export interface FootnoteRef {
  /** Unique within the manuscript: `${chapterOrder}:${localId}`. */
  key: string;
  /** Rendered HTML of the note body. */
  html: string;
  chapterOrder: number;
}

/** A citation occurrence, before rendering. */
export interface CitationRef {
  /** BibTeX key. */
  citeKey: string;
  /** Locator suffix, e.g. "p. 42". */
  locator: string | null;
  /** True for `[-@key]` — suppress the author name. */
  suppressAuthor: boolean;
  /** True for `@key` used narratively outside brackets. */
  narrative: boolean;
}

/**
 * Result of rendering one chapter. This is the unit that gets cached.
 *
 * `html` still contains numbering *tokens* rather than numbers, so it is
 * independent of every other chapter. That is the whole trick behind
 * "recompiling after editing one chapter changes only what should change":
 * a chapter's cached HTML is byte-identical unless the chapter itself changed.
 */
export interface RenderedChapter {
  entry: SpineEntry;
  /** Tokenised HTML — see numbering.ts for the token grammar. */
  html: string;
  /** sha256 of the source note text plus the render-affecting options. */
  sourceHash: string;
  /** sha256 of `html`. */
  renderHash: string;
  figures: FigureRef[];
  footnotes: FootnoteRef[];
  citations: CitationRef[];
  /** Headings for the table of contents, in document order. */
  headings: HeadingRef[];
  diagnostics: Diagnostic[];
  /**
   * Every vault path this chapter's rendered bytes depend on: the note itself plus
   * any note it transcludes. Editing shared boilerplate must re-render exactly the
   * chapters that include it, and no others.
   */
  dependencies: string[];
}

export interface HeadingRef {
  level: number;
  text: string;
  anchor: string;
  chapterOrder: number;
}

export type ChapterChangeKind = "unchanged" | "renumbered" | "rewritten" | "added" | "removed";

export interface ChapterChange {
  path: string;
  title: string;
  kind: ChapterChangeKind;
  /** Human-readable reason, e.g. "figure numbers shifted by +2". */
  reason?: string;
}

export interface StageTiming {
  stage: string;
  ms: number;
}

export interface CompileResult {
  /** The assembled manuscript, ready to hand to SuperDocs export. */
  html: string;
  meta: ManuscriptMeta;
  spine: SpineEntry[];
  diagnostics: Diagnostic[];
  /** Per-chapter incremental verdict. Proves what a recompile actually touched. */
  changes: ChapterChange[];
  stats: {
    chapters: number;
    words: number;
    figures: number;
    footnotes: number;
    citations: number;
    uniqueSources: number;
    /** Rough page estimate at 300 words/page — a claim we can defend, not a measurement. */
    estimatedPages: number;
    bytes: number;
  };
  timings: StageTiming[];
  /** True when nothing blocked the compile. Errors always make this false. */
  ok: boolean;
}
