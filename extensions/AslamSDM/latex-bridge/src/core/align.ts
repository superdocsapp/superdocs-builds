import { TexSegment, AlignedChunk, ChangePatch, PatchResult, htmlToLatex, normalize } from "./writeback";

export interface ProjectFiles {
  [relativePath: string]: string;
}

export interface Change {
  change_id: string;
  chunk_id: string;
  operation: string;
  old_html: string;
  new_html: string;
}

export interface AlignmentPlan {
  align: (change: Change) => AlignedChunk | undefined;
  latexFromHtml: (html: string, file: string) => string;
}

/**
 * Segment-per-file index. Alignment is content-based: the chunk's visible
 * text (normalized) is subsequence-matched against every segment in every
 * file; the best match >= 70% wins. Falls back to positional index when the
 * chunk has no extractable text (e.g. an empty insertion point).
 */
export function buildAlignment(files: ProjectFiles, segments: Map<string, TexSegment[]>): AlignmentPlan {
  const footnoteBodies = new Map<string, string[]>();
  for (const [file, content] of Object.entries(files)) {
    footnoteBodies.set(file, extractFootnoteBodies(content));
  }

  const index: { file: string; segment: TexSegment; segWords: string[] }[] = [];
  for (const [file, segs] of segments) {
    for (const seg of segs) {
      const segWords = normalize(seg.text).split(" ").filter(Boolean);
      if (segWords.length > 0) {
        index.push({ file, segment: seg, segWords });
      }
    }
  }

  return {
    align: (change) => {
      const words = visibleWords(change.old_html);
      if (words.length === 0) {
        const n = parseInt(change.chunk_id, 10);
        const candidates = index.filter((e) => e.segment.index === n);
        if (candidates.length === 1) {
          return chunkOf(candidates[0]);
        }
        return undefined;
      }
      let best: { file: string; segment: TexSegment; segWords: string[] } | undefined;
      let bestScore = 0;
      for (const entry of index) {
        const score = subsequenceScore(words, entry.segWords);
        if (score > bestScore) {
          bestScore = score;
          best = entry;
        }
      }
      return bestScore >= 0.7 && best ? chunkOf(best) : undefined;
    },
    latexFromHtml: (html, file) => htmlToLatex(html, footnoteBodies.get(file) ?? []),
  };

  function chunkOf(entry: { file: string; segment: TexSegment }): AlignedChunk {
    return {
      chunkId: entry.segment.index.toString(),
      file: entry.file,
      segmentIndex: entry.segment.index,
      start: entry.segment.start,
      end: entry.segment.end,
    };
  }
}

export function extractFootnoteBodies(content: string): string[] {
  const out: string[] = [];
  const re = /\\footnote\{([\s\S]*?)\}/g;
  for (let m = re.exec(content); m; m = re.exec(content)) {
    out.push(m[1]);
  }
  return out;
}

/** Visible text of chunk HTML: math (data-latex spans) inner renderings dropped, entities decoded. */
export function visibleWords(html: string): string[] {
  const noMathInner = html.replace(/<span[^>]*data-latex="[^"]*"[^>]*>.*?<\/span>/gi, " ");
  const withoutTags = noMathInner.replace(/<[^>]+>/g, " ");
  return normalize(withoutTags).split(" ").filter(Boolean);
}

export function subsequenceScore(query: string[], corpus: string[]): number {
  let i = 0;
  let hits = 0;
  for (const w of corpus) {
    if (i < query.length && w === query[i]) {
      hits += 1;
      i += 1;
    }
  }
  return hits / query.length;
}

/** Collapse whitespace runs to single spaces, remembering each output byte's source offset. */
export function collapseWithMap(text: string): { collapsed: string; map: number[] } {
  let collapsed = "";
  const map: number[] = [];
  let i = 0;
  while (i < text.length) {
    if (/\s/.test(text[i])) {
      while (i < text.length && /\s/.test(text[i])) i += 1;
      if (collapsed && collapsed[collapsed.length - 1] !== " " && i < text.length) {
        collapsed += " ";
        map.push(i - 1);
      }
    } else {
      collapsed += text[i];
      map.push(i);
      i += 1;
    }
  }
  return { collapsed, map };
}

/** Byte-exact span edit: replace only the changed text run inside the segment, keeping everything else. */
export function planSpanPatch(
  segmentText: string,
  segStart: number,
  oldLatex: string,
  newLatex: string
): { start: number; end: number; replacement: string } | undefined {
  const oldTrim = oldLatex.trim();
  const newTrim = newLatex.trim();
  if (!oldTrim) return undefined;
  const { collapsed, map } = collapseWithMap(segmentText);
  const needle = collapseWithMap(oldTrim).collapsed;
  const idx = collapsed.indexOf(needle);
  if (idx < 0) return undefined;
  const start = segStart + map[idx];
  const end = segStart + map[idx + needle.length - 1] + 1;
  return { start, end, replacement: newTrim };
}

function blockCount(html: string): number {
  const re = /<(?:p|h[1-6]|blockquote|ul|ol|li|pre)\b/g;
  const m = html.match(re);
  return m ? m.length : 0;
}

export function planPatches(
  changes: Change[],
  plan: AlignmentPlan,
  files: ProjectFiles
): { patches: ChangePatch[]; unresolved: Change[] } {
  const patches: ChangePatch[] = [];
  const unresolved: Change[] = [];
  for (const change of changes) {
    const aligned = plan.align(change);
    if (!aligned) {
      unresolved.push(change);
      continue;
    }
    const oldLatex = plan.latexFromHtml(change.old_html, aligned.file);
    const newLatex = plan.latexFromHtml(change.new_html, aligned.file);
    const oldNorm = normalize(oldLatex);
    const newNorm = normalize(newLatex);
    const addedBlocks = blockCount(change.new_html) - blockCount(change.old_html);
    const appendsAfterOld =
      addedBlocks > 0 && newNorm.startsWith(oldNorm) && newNorm.length > oldNorm.length;
    const pureInsert = oldNorm.length === 0 || appendsAfterOld;
    if (pureInsert) {
      const remainder = appendsAfterOld ? newLatex.slice(oldLatex.length) : newLatex;
      patches.push({
        changeId: change.change_id,
        chunkId: change.chunk_id,
        operation: "insert",
        file: aligned.file,
        start: aligned.end,
        end: aligned.end,
        replacement: `\n\n${remainder.trim()}`,
      });
    } else {
      const span = planSpanPatch(
        files[aligned.file].slice(aligned.start, aligned.end),
        aligned.start,
        oldLatex,
        newLatex
      );
      if (span) {
        patches.push({
          changeId: change.change_id,
          chunkId: change.chunk_id,
          operation: "edit",
          file: aligned.file,
          start: span.start,
          end: span.end,
          replacement: span.replacement,
        });
      } else {
        patches.push({
          changeId: change.change_id,
          chunkId: change.chunk_id,
          operation: "edit",
          file: aligned.file,
          start: aligned.start,
          end: aligned.end,
          replacement: newLatex.trim(),
        });
      }
    }
  }
  return { patches, unresolved };
}

export function applyPatches(files: ProjectFiles, patches: ChangePatch[]): PatchResult {
  const resultFiles = new Map<string, string>(Object.entries(files));
  const applied: ChangePatch[] = [];
  const byFile = new Map<string, ChangePatch[]>();
  for (const p of patches) {
    const arr = byFile.get(p.file) ?? [];
    arr.push(p);
    byFile.set(p.file, arr);
  }
  for (const [file, filePatches] of byFile) {
    const sorted = [...filePatches].sort((a, b) => a.start - b.start);
    let content = resultFiles.get(file) ?? "";
    for (const patch of sorted) {
      content = content.slice(0, patch.start) + patch.replacement + content.slice(patch.end);
    }
    resultFiles.set(file, content);
    for (const p of sorted) applied.push(p);
  }
  return { files: resultFiles, applied, unresolved: [] };
}
