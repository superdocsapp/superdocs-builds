import type { AlignedBlock, Block, Chapter, ConfidenceLevel } from "../types.js";

/**
 * Aligns a chapter's source blocks to a translated chapter's blocks.
 *
 * Paragraph 1 in the source is not reliably paragraph 1 in the translation
 * -- translation changes length and can merge or split blocks (Phase 14 of
 * the engineering plan). This is deliberately NOT a semantic/NLP aligner;
 * it's a structural one, in three tiers of decreasing confidence:
 *
 *   1. Same block count AND same kind sequence -> direct 1:1 index mapping.
 *      High confidence: the structural shape survived translation intact.
 *
 *   2. Different shape -> proportional position mapping (block i maps to
 *      the same *relative* position in the translation), refined by
 *      searching a small window for a block of the same kind (a verse
 *      block should still land near another verse block). Medium
 *      confidence.
 *
 *   3. No same-kind block found nearby -> mapped to the nearest position
 *      anyway, but flagged reviewRequired = true. This is intentional:
 *      when uncertain, say so rather than pretending certainty.
 */

const SEARCH_WINDOW = 2;

function proportionalIndex(sourceIndex: number, sourceLength: number, targetLength: number): number {
  if (sourceLength <= 1 || targetLength <= 1) return 0;
  return Math.round((sourceIndex * (targetLength - 1)) / (sourceLength - 1));
}

export function alignChapterBlocks(sourceChapterId: string, sourceBlocks: Block[], translatedBlocks: Block[]): AlignedBlock[] {
  if (translatedBlocks.length === 0) {
    return sourceBlocks.map((b) => ({
      sourceChapterId,
      sourceBlockId: b.id,
      translatedBlockId: null,
      confidence: "low" as ConfidenceLevel,
      reviewRequired: true,
    }));
  }

  const sameShape =
    sourceBlocks.length === translatedBlocks.length && sourceBlocks.every((b, i) => b.kind === translatedBlocks[i]?.kind);

  if (sameShape) {
    return sourceBlocks.map((b, i) => ({
      sourceChapterId,
      sourceBlockId: b.id,
      translatedBlockId: translatedBlocks[i]!.id,
      confidence: "high" as ConfidenceLevel,
      reviewRequired: false,
    }));
  }

  return sourceBlocks.map((b, i) => {
    const target = proportionalIndex(i, sourceBlocks.length, translatedBlocks.length);
    const lo = Math.max(0, target - SEARCH_WINDOW);
    const hi = Math.min(translatedBlocks.length - 1, target + SEARCH_WINDOW);

    let best: { index: number; distance: number } | null = null;
    for (let j = lo; j <= hi; j++) {
      const candidate = translatedBlocks[j];
      if (candidate && candidate.kind === b.kind) {
        const distance = Math.abs(j - target);
        if (!best || distance < best.distance) best = { index: j, distance };
      }
    }

    if (best) {
      return {
        sourceChapterId,
        sourceBlockId: b.id,
        translatedBlockId: translatedBlocks[best.index]!.id,
        confidence: "medium" as ConfidenceLevel,
        reviewRequired: false,
      };
    }

    const fallback = translatedBlocks[Math.max(0, Math.min(translatedBlocks.length - 1, target))]!;
    return {
      sourceChapterId,
      sourceBlockId: b.id,
      translatedBlockId: fallback.id,
      confidence: "low" as ConfidenceLevel,
      reviewRequired: true,
    };
  });
}

export interface ChapterAlignmentResult {
  sourceChapterId: string;
  translatedChapterId: string | null;
  blockAlignments: AlignedBlock[];
}

/**
 * Aligns chapters by index/order (translations overwhelmingly preserve
 * chapter count and order even when internal structure shifts). A source
 * chapter with no corresponding translated chapter gets an entirely
 * reviewRequired block alignment rather than being silently skipped.
 */
export function alignManuscripts(sourceChapters: Chapter[], translatedChapters: Chapter[]): ChapterAlignmentResult[] {
  return sourceChapters.map((sourceChapter, i) => {
    const translatedChapter = translatedChapters[i] ?? null;
    return {
      sourceChapterId: sourceChapter.id,
      translatedChapterId: translatedChapter?.id ?? null,
      blockAlignments: alignChapterBlocks(sourceChapter.id, sourceChapter.blocks, translatedChapter?.blocks ?? []),
    };
  });
}
