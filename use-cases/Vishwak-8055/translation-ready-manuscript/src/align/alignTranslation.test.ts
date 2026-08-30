import { describe, expect, it } from "vitest";
import type { Block } from "../types.js";
import { alignChapterBlocks, alignManuscripts } from "./alignTranslation.js";

function block(id: string, kind: Block["kind"], text: string): Block {
  return { id, kind, text, spans: [{ text }], hasEmphasis: false };
}

describe("alignChapterBlocks", () => {
  it("aligns 1:1 with high confidence when block count and kind sequence match", () => {
    const source = [block("s1", "paragraph", "a"), block("s2", "dialogue", "b"), block("s3", "verse", "c")];
    const translated = [block("t1", "paragraph", "a-fr"), block("t2", "dialogue", "b-fr"), block("t3", "verse", "c-fr")];
    const result = alignChapterBlocks("ch01", source, translated);
    expect(result).toHaveLength(3);
    expect(result.map((r) => r.translatedBlockId)).toEqual(["t1", "t2", "t3"]);
    expect(result.every((r) => r.confidence === "high" && !r.reviewRequired)).toBe(true);
  });

  it("falls back to proportional + same-kind search with medium confidence when shapes differ", () => {
    // Source has 3 blocks; translation split the middle paragraph into two, so counts differ.
    const source = [block("s1", "paragraph", "a"), block("s2", "dialogue", "b"), block("s3", "verse", "c")];
    const translated = [
      block("t1", "paragraph", "a-fr"),
      block("t2", "dialogue", "b-fr-part1"),
      block("t3", "dialogue", "b-fr-part2"),
      block("t4", "verse", "c-fr"),
    ];
    const result = alignChapterBlocks("ch01", source, translated);
    // Shape-matching is evaluated once for the whole chapter, not block-by-block, so once
    // counts differ every block in this chapter goes through the windowed-search tier --
    // even block 0, whose nearest same-kind neighbor happens to be an exact index match.
    expect(result[0]?.confidence).toBe("medium");
    expect(result[0]?.translatedBlockId).toBe("t1");
    expect(result[1]?.translatedBlockId).toMatch(/^t[23]$/); // one of the two dialogue blocks
    expect(result[2]?.translatedBlockId).toBe("t4"); // the verse block, found via same-kind window search
    expect(result.some((r) => r.reviewRequired)).toBe(false);
  });

  it("flags reviewRequired with low confidence when no same-kind block exists nearby, rather than guessing silently", () => {
    const source = [block("s1", "verse", "a poem")];
    const translated = [block("t1", "paragraph", "prose only, no verse in this translation")];
    const result = alignChapterBlocks("ch01", source, translated);
    expect(result).toHaveLength(1);
    expect(result[0]?.reviewRequired).toBe(true);
    expect(result[0]?.confidence).toBe("low");
    // Still gives a best-effort fallback location rather than null, so a reviewer has somewhere to look.
    expect(result[0]?.translatedBlockId).toBe("t1");
  });

  it("marks every block reviewRequired with a null target when the translation is empty", () => {
    const source = [block("s1", "paragraph", "a"), block("s2", "paragraph", "b")];
    const result = alignChapterBlocks("ch01", source, []);
    expect(result).toHaveLength(2);
    expect(result.every((r) => r.reviewRequired && r.translatedBlockId === null)).toBe(true);
  });
});

describe("alignManuscripts", () => {
  it("aligns chapters by order and flags a wholly-missing chapter as reviewRequired rather than skipping it", () => {
    const sourceChapters = [
      { id: "ch01", index: 1, title: "One", blocks: [block("s1", "paragraph", "a")] },
      { id: "ch02", index: 2, title: "Two", blocks: [block("s2", "paragraph", "b")] },
    ];
    const translatedChapters = [{ id: "tch01", index: 1, title: "Uno", blocks: [block("t1", "paragraph", "a-es")] }];
    const result = alignManuscripts(sourceChapters, translatedChapters);
    expect(result).toHaveLength(2);
    expect(result[0]?.translatedChapterId).toBe("tch01");
    expect(result[1]?.translatedChapterId).toBeNull();
    expect(result[1]?.blockAlignments.every((b) => b.reviewRequired)).toBe(true);
  });
});
