import { describe, expect, it } from "vitest";
import {
  countTextTokens,
  documentText,
  estimateWholeDocumentTokens,
  measure,
  savings,
  tokenizeText
} from "../shared/tokens.js";
import { buildDocument, TARGET_PARAGRAPH } from "../shared/corpus.js";
import { resolveSelection } from "../shared/selection.js";
import type { DocumentSnapshot, JobWork } from "../shared/types.js";

const DOCUMENT: DocumentSnapshot = {
  paragraphs: [
    { id: "p0", text: "Quarterly Review" },
    { id: "p1", text: "The quarterly review covers three business units." },
    { id: "p2", text: "Headcount grew by eleven people." }
  ]
};

describe("countTextTokens", () => {
  it("counts nothing for an empty string", () => {
    expect(countTextTokens("")).toBe(0);
  });

  it("is deterministic and grows with the text", () => {
    const short = countTextTokens("The quarterly review covers three business units.");
    const long = countTextTokens(
      "The quarterly review covers three business units and their operating results."
    );

    expect(short).toBeGreaterThan(0);
    expect(long).toBeGreaterThan(short);
    expect(countTextTokens("abc")).toBe(countTextTokens("abc"));
  });

  it("is a real tokenization, not a length heuristic", () => {
    // " the" is a single BPE token; the character count is not.
    expect(countTextTokens(" the")).toBe(1);
    expect(countTextTokens("hello world")).toBe(2);
  });
});

describe("documentText", () => {
  it("joins the paragraphs so the count covers the whole body", () => {
    expect(documentText(DOCUMENT)).toContain("Quarterly Review");
    expect(documentText(DOCUMENT)).toContain("Headcount grew by eleven people.");
  });
});

describe("savings", () => {
  it("is the difference, and that difference over the whole-document cost", () => {
    expect(savings(1000, 250)).toEqual({ tokens: 750, ratio: 0.75 });
  });

  it("goes negative when the surgical edit cost more", () => {
    const result = savings(100, 150);

    expect(result.tokens).toBe(-50);
    expect(result.ratio).toBeCloseTo(-0.5, 10);
  });

  it("does not divide by zero", () => {
    expect(savings(0, 0)).toEqual({ tokens: 0, ratio: 0 });
  });
});

describe("estimateWholeDocumentTokens", () => {
  it("adds the untouched remainder twice: once read, once written", () => {
    // surgical 1000, document 500, selection 100 -> 1000 + 2 * 400
    expect(estimateWholeDocumentTokens(1000, 500, 100).tokens).toBe(1800);
  });

  it("never claims the estimate was measured", () => {
    expect(estimateWholeDocumentTokens(1000, 500, 100).source).toBe("estimated");
  });

  it("collapses to the surgical cost when the selection is the whole document", () => {
    expect(estimateWholeDocumentTokens(1000, 500, 500).tokens).toBe(1000);
  });

  it("does not go below the surgical cost when the selection tokenizes larger", () => {
    expect(estimateWholeDocumentTokens(1000, 500, 900).tokens).toBe(1000);
  });

  it("grows with the document while the surgical cost stays put", () => {
    const small = estimateWholeDocumentTokens(1000, 500, 100).tokens;
    const large = estimateWholeDocumentTokens(1000, 50_000, 100).tokens;

    expect(large).toBeGreaterThan(small * 10);
  });
});

describe("measure", () => {
  const selection = { paragraphIds: ["p1"], text: DOCUMENT.paragraphs[1]!.text };

  function work(sections: number, text: string): JobWork {
    return {
      sectionsChanged: sections,
      output: { tokens: countTextTokens(text), source: "tokenized", method: "test fixture" }
    };
  }

  const surgicalWork = work(1, "The review covers three units.");

  it("labels the reported cost as measured and passes it through unchanged", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 87_303
    });

    expect(result.reported.surgical?.tokens).toBe(87_303);
    expect(result.reported.surgical?.source).toBe("measured");
    expect(result.reported.surgical?.method).toContain("cumulative_tokens");
  });

  it("returns null rather than zero when SuperDocs reported no cost", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: null
    });

    expect(result.reported.surgical).toBeNull();
    expect(result.reported.wholeDocument).toBeNull();
    expect(result.reported.savings).toBeNull();
  });

  it("still compares written output when the reported cost is missing", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: null
    });

    expect(result.written.surgical?.tokens).toBe(surgicalWork.output.tokens);
    expect(result.written.wholeDocument?.tokens).toBe(result.document.tokens);
    expect(result.written.savings!.ratio).toBeGreaterThan(0);
  });

  it("falls back to the estimate, labelled, when no regeneration was run", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 1000
    });

    expect(result.reported.wholeDocument?.source).toBe("estimated");
    expect(result.reported.wholeDocument?.tokens).toBe(
      estimateWholeDocumentTokens(1000, result.document.tokens, result.selection.tokens).tokens
    );
  });

  it("uses the real regeneration cost when one was measured, and says so", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 231_075,
      wholeDocumentWork: work(300, "regenerated body text"),
      reportedWholeDocumentTokens: 1_009_856
    });

    expect(result.reported.wholeDocument?.source).toBe("measured");
    expect(result.reported.wholeDocument?.tokens).toBe(1_009_856);
    expect(result.reported.savings?.tokens).toBe(1_009_856 - 231_075);
    expect(result.reported.savings?.ratio).toBeCloseTo(0.7712, 4);
  });

  it("prefers a measured regeneration's written output over the estimate", () => {
    const measured = work(300, "regenerated body text");
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 1000,
      wholeDocumentWork: measured,
      reportedWholeDocumentTokens: 2000
    });

    expect(result.written.wholeDocument).toEqual(measured.output);
    expect(result.sections).toEqual({ surgical: 1, wholeDocument: 300 });
  });

  it("reports a null regeneration cost without discarding the work it did", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 1000,
      wholeDocumentWork: work(300, "regenerated body text"),
      reportedWholeDocumentTokens: null
    });

    expect(result.reported.wholeDocument).toBeNull();
    expect(result.reported.savings).toBeNull();
    expect(result.sections.wholeDocument).toBe(300);
    expect(result.written.savings).not.toBeNull();
  });

  it("tokenizes the selection and the document rather than measuring them", () => {
    const result = measure({
      document: DOCUMENT,
      selection,
      surgicalWork,
      reportedSurgicalTokens: 1000
    });

    expect(result.selection.source).toBe("tokenized");
    expect(result.document.source).toBe("tokenized");
    expect(result.selection.tokens).toBe(countTextTokens(selection.text));
    expect(result.document.tokens).toBe(countTextTokens(documentText(DOCUMENT)));
    expect(result.document.tokens).toBeGreaterThan(result.selection.tokens);
  });
});

describe("tokenizeText", () => {
  it("names what it counted, so the UI can show it", () => {
    expect(tokenizeText("hello", "selected text").method).toContain("selected text");
  });
});

describe("the benchmark corpus", () => {
  it("is deterministic: the same size gives byte-identical text", () => {
    expect(documentText(buildDocument(3))).toBe(documentText(buildDocument(3)));
  });

  it("scales with the requested page count", () => {
    const three = countTextTokens(documentText(buildDocument(3)));
    const ten = countTextTokens(documentText(buildDocument(10)));

    expect(ten).toBeGreaterThan(three * 2.5);
  });

  it("contains exactly one copy of the paragraph the benchmark rewrites", () => {
    for (const pages of [3, 10, 50]) {
      const document = buildDocument(pages);
      const hits = document.paragraphs.filter((p) => p.text === TARGET_PARAGRAPH);

      expect(hits, `${pages} pages`).toHaveLength(1);
      expect(resolveSelection(document, TARGET_PARAGRAPH).paragraphIds).toHaveLength(1);
    }
  });

  it("places the target past the middle, so reaching it means reading the document", () => {
    const document = buildDocument(50);
    const index = document.paragraphs.findIndex((p) => p.text === TARGET_PARAGRAPH);

    expect(index / document.paragraphs.length).toBeGreaterThan(0.5);
  });
});
