import { describe, expect, it } from "vitest";
import {
  assertInstruction,
  buildSurgicalMessage,
  checkScope,
  htmlToText,
  InvalidSelectionError,
  resolveSelection,
  toDocumentHtml
} from "../shared/selection.js";
import type { DocumentSnapshot, ProposedChange } from "../shared/types.js";

const DOCUMENT: DocumentSnapshot = {
  paragraphs: [
    { id: "p0", text: "Quarterly Review" },
    { id: "p1", text: "The quarterly review covers three business units." },
    {
      id: "p2",
      text:
        "Notwithstanding the foregoing, it should be noted that the parties hereto have " +
        "undertaken a not insubstantial number of initiatives."
    },
    { id: "p3", text: "Headcount grew by eleven people, concentrated in engineering." }
  ]
};

function change(overrides: Partial<ProposedChange>): ProposedChange {
  return {
    changeId: "c1",
    chunkId: "k1",
    operation: "edit",
    oldHtml: "",
    newHtml: "",
    oldText: "",
    newText: "",
    explanation: "",
    ...overrides
  };
}

describe("resolveSelection", () => {
  it("finds the paragraph a whole-paragraph selection covers", () => {
    const selection = resolveSelection(DOCUMENT, DOCUMENT.paragraphs[2]!.text);

    expect(selection.paragraphIds).toEqual(["p2"]);
    expect(selection.text).toBe(DOCUMENT.paragraphs[2]!.text);
  });

  it("finds the paragraph a partial selection sits inside", () => {
    expect(resolveSelection(DOCUMENT, "a not insubstantial number").paragraphIds).toEqual(["p2"]);
  });

  it("covers every paragraph a multi-paragraph selection spans", () => {
    const dragged = `${DOCUMENT.paragraphs[1]!.text}\n${DOCUMENT.paragraphs[2]!.text}`;

    expect(resolveSelection(DOCUMENT, dragged).paragraphIds).toEqual(["p1", "p2"]);
  });

  it("survives the line breaks and stray whitespace a real drag introduces", () => {
    const messy = "  a not\n   insubstantial\tnumber  ";

    expect(resolveSelection(DOCUMENT, messy).paragraphIds).toEqual(["p2"]);
  });

  it("rejects an empty selection with a message aimed at the user", () => {
    expect(() => resolveSelection(DOCUMENT, "   \n  ")).toThrow(InvalidSelectionError);
    expect(() => resolveSelection(DOCUMENT, "")).toThrow(/Nothing is selected/u);
  });

  it("rejects a selection that is not in the document rather than guessing", () => {
    expect(() => resolveSelection(DOCUMENT, "text from some other document")).toThrow(
      /was not found in the document/u
    );
  });
});

describe("assertInstruction", () => {
  it("returns the trimmed instruction", () => {
    expect(assertInstruction("  Make this more concise.  ")).toBe("Make this more concise.");
  });

  it("rejects an empty instruction", () => {
    expect(() => assertInstruction("   ")).toThrow(/Enter a rewrite instruction/u);
  });
});

describe("buildSurgicalMessage", () => {
  it("carries the selection verbatim and delimited, plus the instruction", () => {
    const selection = resolveSelection(DOCUMENT, DOCUMENT.paragraphs[2]!.text);
    const message = buildSurgicalMessage(selection, "Make this more concise.");

    expect(message).toContain(DOCUMENT.paragraphs[2]!.text);
    expect(message).toContain("Instruction: Make this more concise.");
    expect(message).toContain("<<<SELECTION");
    expect(message).toContain("SELECTION>>>");
  });

  it("tells the model to leave everything else alone", () => {
    const selection = resolveSelection(DOCUMENT, "Headcount grew");

    expect(buildSurgicalMessage(selection, "shorten")).toMatch(/ONLY the text delimited/u);
  });
});

describe("toDocumentHtml", () => {
  it("emits one paragraph element per paragraph", () => {
    expect(toDocumentHtml(DOCUMENT).match(/<p>/gu)).toHaveLength(4);
  });

  it("escapes markup in the document instead of passing it through", () => {
    const html = toDocumentHtml({ paragraphs: [{ id: "p0", text: "a <script> & b" }] });

    expect(html).toBe("<p>a &lt;script&gt; &amp; b</p>");
  });
});

describe("checkScope", () => {
  const selection = resolveSelection(DOCUMENT, DOCUMENT.paragraphs[2]!.text);

  it("accepts a change to the selected paragraph", () => {
    const report = checkScope(
      [change({ oldText: DOCUMENT.paragraphs[2]!.text, newText: "Shorter." })],
      DOCUMENT,
      selection
    );

    expect(report.inScope).toHaveLength(1);
    expect(report.outOfScope).toHaveLength(0);
  });

  it("accepts a change to part of the selected paragraph", () => {
    const report = checkScope(
      [change({ oldText: "a not insubstantial number of initiatives." })],
      DOCUMENT,
      selection
    );

    expect(report.inScope).toHaveLength(1);
  });

  it("flags a change to a paragraph the user did not select", () => {
    const report = checkScope(
      [change({ oldText: DOCUMENT.paragraphs[3]!.text, newText: "Headcount rose." })],
      DOCUMENT,
      selection
    );

    expect(report.inScope).toHaveLength(0);
    expect(report.outOfScope).toHaveLength(1);
  });

  it("treats a change it cannot map back to the selection as out of scope", () => {
    const report = checkScope([change({ oldText: "" })], DOCUMENT, selection);

    expect(report.outOfScope).toHaveLength(1);
  });

  it("separates the in-scope change from the out-of-scope one in a mixed batch", () => {
    const report = checkScope(
      [
        change({ changeId: "a", oldText: DOCUMENT.paragraphs[2]!.text }),
        change({ changeId: "b", oldText: DOCUMENT.paragraphs[1]!.text })
      ],
      DOCUMENT,
      selection
    );

    expect(report.inScope.map((c) => c.changeId)).toEqual(["a"]);
    expect(report.outOfScope.map((c) => c.changeId)).toEqual(["b"]);
  });
});

describe("htmlToText", () => {
  it("recovers the text SuperDocs wrapped in a chunk element", () => {
    expect(htmlToText('<p data-chunk-id="7">Hello  there</p>')).toBe("Hello there");
  });

  it("decodes the entities the document HTML escaped on the way out", () => {
    expect(htmlToText("<p>a &lt;b&gt; &amp; c</p>")).toBe("a <b> & c");
  });
});
