/**
 * The compile cache, and the evidence that an incremental compile is honest.
 *
 * The manifest records, per chapter: the hash of everything it was rendered from,
 * the hash of the tokenised render, the hash of the render after numbering, and
 * the files it depends on. On the next compile we can therefore say, per chapter,
 * one of exactly four things — and prove each:
 *
 *   unchanged   source hash same, resolved hash same  -> not re-rendered, bytes identical
 *   renumbered  source hash same, resolved hash moved -> reused render, numbers shifted
 *   rewritten   source hash moved                      -> re-rendered from markdown
 *   added/removed                                      -> spine membership changed
 *
 * "Recompiling after editing one chapter changes only what should change" is not a
 * claim here, it is a diff the compiler prints and the tests assert.
 *
 * The manifest is also the resume point: it is written after every compile, so a
 * process killed mid-run loses at most the chapters it had not finished rendering.
 */

import type {
  ChapterChange,
  CitationRef,
  FigureRef,
  FootnoteRef,
  HeadingRef,
  RenderedChapter,
} from "./types";

export const MANIFEST_VERSION = 3;

export interface ManifestChapter {
  path: string;
  title: string;
  order: number;
  sourceHash: string;
  renderHash: string;
  /** Hash of the chapter after numbering — what actually lands in the output. */
  resolvedHash: string;
  dependencies: string[];
  /**
   * The chapter's structural metadata, stored in full rather than re-derived.
   *
   * A reused chapter is never re-parsed, so everything the assembly pass needs
   * from it — figures, footnote bodies, citation occurrences, headings — has to
   * survive in the manifest. Re-deriving it by regex over cached HTML was the
   * first design here and it silently lost footnote bodies, which live outside
   * the chapter's own markup.
   */
  figures: FigureRef[];
  footnotes: FootnoteRef[];
  citations: CitationRef[];
  headings: HeadingRef[];
}

export interface Manifest {
  version: number;
  /** ISO timestamp of the compile that wrote this manifest. */
  compiledAt: string;
  /** Hash of the compile options that affect rendered bytes. */
  optionsHash: string;
  spineHash: string;
  chapters: Record<string, ManifestChapter>;
  /** Cached tokenised HTML per chapter path. */
  renders: Record<string, string>;
  /** sha256(image bytes) -> the URL SuperDocs handed back. Saves re-uploading. */
  imageUrls: Record<string, string>;
  /** Last completed compile's assembled output hash. */
  outputHash: string | null;
}

export function emptyManifest(): Manifest {
  return {
    version: MANIFEST_VERSION,
    compiledAt: new Date(0).toISOString(),
    optionsHash: "",
    spineHash: "",
    chapters: {},
    renders: {},
    imageUrls: {},
    outputHash: null,
  };
}

/** A manifest from an older build, or a corrupt one, is discarded, not migrated. */
export function loadManifest(raw: string | null): Manifest {
  if (!raw) return emptyManifest();
  try {
    const parsed = JSON.parse(raw) as Manifest;
    if (parsed?.version !== MANIFEST_VERSION) return emptyManifest();
    if (typeof parsed.chapters !== "object" || typeof parsed.renders !== "object") {
      return emptyManifest();
    }
    return {
      ...emptyManifest(),
      ...parsed,
      imageUrls: parsed.imageUrls ?? {},
    };
  } catch {
    return emptyManifest();
  }
}

export interface ReusePlan {
  /** Chapter paths whose cached render may be reused verbatim. */
  reusable: Set<string>;
  /** Why each non-reusable chapter must be re-rendered. */
  reasons: Map<string, string>;
}

/**
 * Decide which chapters can skip markdown rendering.
 *
 * A chapter is reusable when its own source is unchanged AND every file it
 * transcludes is unchanged AND the render-affecting options are unchanged. Note
 * what is deliberately NOT in that list: the contents of other chapters. A chapter
 * whose neighbours changed keeps its cached render and gets renumbered instead.
 */
export function planReuse(
  manifest: Manifest,
  optionsHash: string,
  currentHashes: Map<string, string>,
  spinePaths: string[],
): ReusePlan {
  const reusable = new Set<string>();
  const reasons = new Map<string, string>();

  if (manifest.optionsHash !== optionsHash) {
    for (const p of spinePaths) reasons.set(p, "compile options changed");
    return { reusable, reasons };
  }

  for (const path of spinePaths) {
    const entry = manifest.chapters[path];
    if (!entry) {
      reasons.set(path, "new on the spine");
      continue;
    }
    if (manifest.renders[path] === undefined) {
      reasons.set(path, "no cached render");
      continue;
    }
    const current = currentHashes.get(path);
    if (current === undefined) {
      reasons.set(path, "source unreadable");
      continue;
    }
    if (current !== entry.sourceHash) {
      reasons.set(path, "source edited");
      continue;
    }
    reusable.add(path);
  }
  return { reusable, reasons };
}

/**
 * Compare this compile against the manifest and produce the per-chapter verdict.
 * `resolvedHashes` are the post-numbering hashes of this compile.
 */
export function diffAgainstManifest(
  manifest: Manifest,
  chapters: RenderedChapter[],
  resolvedHashes: Map<string, string>,
  /** Why the reuse plan rejected each chapter, so the report can say so exactly. */
  reasons: Map<string, string> = new Map(),
): ChapterChange[] {
  const changes: ChapterChange[] = [];
  const seen = new Set<string>();

  for (const ch of chapters) {
    const path = ch.entry.path;
    seen.add(path);
    const before = manifest.chapters[path];
    const resolved = resolvedHashes.get(path) ?? "";

    if (!before) {
      changes.push({ path, title: ch.entry.title, kind: "added" });
      continue;
    }
    if (before.sourceHash !== ch.sourceHash) {
      changes.push({
        path,
        title: ch.entry.title,
        kind: "rewritten",
        reason: reasons.get(path) ?? "the note (or something it transcludes) was edited",
      });
      continue;
    }
    if (before.resolvedHash !== resolved) {
      changes.push({
        path,
        title: ch.entry.title,
        kind: "renumbered",
        reason: describeRenumber(before, ch, resolved),
      });
      continue;
    }
    changes.push({ path, title: ch.entry.title, kind: "unchanged" });
  }

  for (const [path, before] of Object.entries(manifest.chapters)) {
    if (!seen.has(path)) {
      changes.push({ path, title: before.title, kind: "removed" });
    }
  }

  return changes;
}

function describeRenumber(
  before: ManifestChapter,
  ch: RenderedChapter,
  _resolved: string,
): string {
  const figuresMoved =
    before.figures.map((f) => f.key).join("|") !== ch.figures.map((f) => f.key).join("|");
  const footnotesMoved =
    before.footnotes.map((f) => f.key).join("|") !== ch.footnotes.map((f) => f.key).join("|");
  if (figuresMoved || footnotesMoved) {
    return "its own figure or footnote set changed";
  }
  return "numbering shifted because an earlier chapter changed; the prose is untouched";
}

export function buildManifest(
  previous: Manifest,
  optionsHash: string,
  spineHash: string,
  chapters: RenderedChapter[],
  resolvedHashes: Map<string, string>,
  outputHash: string,
): Manifest {
  const out: Manifest = {
    version: MANIFEST_VERSION,
    compiledAt: new Date().toISOString(),
    optionsHash,
    spineHash,
    chapters: {},
    renders: {},
    imageUrls: { ...previous.imageUrls },
    outputHash,
  };
  for (const ch of chapters) {
    const path = ch.entry.path;
    out.chapters[path] = {
      path,
      title: ch.entry.title,
      order: ch.entry.order,
      sourceHash: ch.sourceHash,
      renderHash: ch.renderHash,
      resolvedHash: resolvedHashes.get(path) ?? "",
      dependencies: ch.dependencies,
      figures: ch.figures,
      footnotes: ch.footnotes,
      citations: ch.citations,
      headings: ch.headings,
    };
    out.renders[path] = ch.html;
  }
  return out;
}

export function summariseChanges(changes: ChapterChange[]): Record<string, number> {
  const counts: Record<string, number> = {
    unchanged: 0,
    renumbered: 0,
    rewritten: 0,
    added: 0,
    removed: 0,
  };
  for (const c of changes) counts[c.kind] = (counts[c.kind] ?? 0) + 1;
  return counts;
}
