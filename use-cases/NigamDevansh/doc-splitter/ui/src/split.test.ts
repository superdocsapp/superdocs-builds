import { describe, expect, it } from "vitest";
import {
  type Cut,
  exportWarning,
  markersNeeded,
  ordered,
  pageBox,
  pageOf,
  partAfter,
  quoteAround,
  applySnap,
  hasWordAt,
  snapToWord,
} from "./split";

const cut = (chunk: string, offset: number): Cut => ({
  chunk_id: chunk,
  offset,
  page: 1,
  line: 1,
  quote: "",
});

describe("how many markers a part count needs", () => {
  it("is one fewer than the parts", () => {
    // Three parts need two cuts: the document already has a beginning and an
    // end, and marking the start of part 1 is a question with one answer.
    expect(markersNeeded(3)).toBe(2);
    expect(markersNeeded(1)).toBe(0);
  });

  it("never goes negative", () => {
    expect(markersNeeded(0)).toBe(0);
  });

  it("names which part each cut opens", () => {
    expect(partAfter(0)).toBe(2);
    expect(partAfter(1)).toBe(3);
  });
});

describe("cuts are kept in document order", () => {
  const order = new Map([
    ["a", 0],
    ["b", 1],
    ["c", 2],
  ]);

  it("sorts by block, then by offset within a block", () => {
    // A reviewer clicks in whatever order they read. Two markers placed
    // back-to-front must still produce parts in document order.
    const sorted = ordered([cut("c", 5), cut("a", 90), cut("b", 3)], order);
    expect(sorted.map((item) => item.chunk_id)).toEqual(["a", "b", "c"]);
  });

  it("orders two cuts inside one paragraph", () => {
    const sorted = ordered([cut("b", 200), cut("b", 40)], order);
    expect(sorted.map((item) => item.offset)).toEqual([40, 200]);
  });

  it("drops an exact repeat rather than making an empty part", () => {
    expect(ordered([cut("b", 40), cut("b", 40)], order)).toHaveLength(1);
  });

  it("keeps two different offsets in the same block", () => {
    expect(ordered([cut("b", 40), cut("b", 41)], order)).toHaveLength(2);
  });
});

describe("the printable page", () => {
  it("uses the real paper size and margins from the .docx", () => {
    const box = pageBox({ width_in: 8.5, height_in: 11, margin_in: { top: 1, right: 1.25, bottom: 1, left: 1.25 } });
    expect(box.width).toBeCloseTo(6 * 96);
    expect(box.height).toBeCloseTo(9 * 96);
  });

  it("falls back to Letter when the format carries no page setup", () => {
    // A .md or .txt master has none, and the preview still has to paginate.
    expect(pageBox(null).width).toBeCloseTo(6.5 * 96);
  });

  it("numbers pages from one", () => {
    expect(pageOf(0, 864)).toBe(1);
    expect(pageOf(863, 864)).toBe(1);
    expect(pageOf(864, 864)).toBe(2);
  });
});

describe("what the reviewer sees for a cut", () => {
  const sentence = "Fees are due Net 30 from the date of invoice receipt.";

  it("shows the text either side, with the cut point marked", () => {
    expect(quoteAround(sentence, 13, 8)).toBe("…are due |Net 30 f…");
  });

  it("shows a mid-word cut as a mid-word cut", () => {
    // Rounding to the nearest word would hide what was actually asked for.
    expect(quoteAround(sentence, 15, 6)).toContain("Ne|t 30");
  });

  it("does not lead with an ellipsis at the very start", () => {
    expect(quoteAround(sentence, 2, 8).startsWith("…")).toBe(false);
  });
});

describe("what the reviewer is told before spending", () => {
  it("says nothing for a small split", () => {
    expect(exportWarning(3, 10)).toBeNull();
  });

  it("warns when a split would spend a lot of operations", () => {
    expect(exportWarning(12, 20)).toContain("12 export operations");
  });

  it("names the limit when the split exceeds it", () => {
    expect(exportWarning(12, 10)).toContain("exceeds the limit of 10");
  });
});

describe("word snapping", () => {
  const line = "Fees are due Net 30 from invoice.";

  it("moves a mid-word cut back to the start of that word", () => {
    // "N|et" → "|Net". Clicking exactly between two letters is fiddly, and the
    // start of the word is what a reviewer usually means.
    expect(snapToWord(line, 14)).toBe(13);
    expect(line.slice(snapToWord(line, 14))).toBe("Net 30 from invoice.");
  });

  it("leaves a cut already at a word start alone", () => {
    expect(snapToWord(line, 13)).toBe(13);
  });

  it("moves a cut in whitespace forward to the next word", () => {
    // Never into the run of spaces: a part starting with a blank is not what
    // the marker showed.
    expect(snapToWord("Fees   are due", 5)).toBe(7);
    expect("Fees   are due".slice(snapToWord("Fees   are due", 5))).toBe("are due");
  });

  it("handles the very start and the very end", () => {
    expect(snapToWord(line, 0)).toBe(0);
    expect(snapToWord(line, line.length)).toBe(line.lastIndexOf("invoice."));
  });

  it("exact mode keeps the character the reviewer picked, mid-word and all", () => {
    expect(applySnap(line, 14, "exact")).toBe(14);
    expect(applySnap(line, 14, "word")).toBe(13);
  });
});

describe("clicking where there is no word", () => {
  it("rejects a position surrounded by whitespace", () => {
    // The gap between two paragraphs resolves to some text node, and cutting
    // there is not what anybody meant.
    expect(hasWordAt("   ", 1)).toBe(false);
  });

  it("accepts a position touching a word on either side", () => {
    expect(hasWordAt("ab", 1)).toBe(true);
    expect(hasWordAt("a ", 1)).toBe(true);
    expect(hasWordAt(" a", 1)).toBe(true);
  });

  it("treats a non-breaking space as whitespace", () => {
    // SuperDocs emits &nbsp; inside paragraphs and \s does not match it.
    expect(hasWordAt("  ", 1)).toBe(false);
  });
});
