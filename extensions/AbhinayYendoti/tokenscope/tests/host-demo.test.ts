// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDemoHost, PARAGRAPH_ATTRIBUTE } from "../src/host/demo.js";
import { HostError } from "../src/host/types.js";
import type { DocumentHost } from "../src/host/types.js";

/**
 * The demo host, against a real DOM.
 *
 * These cover the two things the host is trusted with: reading the selection the
 * user actually made, and refusing to change the document when it is not certain
 * what to change. The pane's whole safety story rests on the second one.
 */

const PARAGRAPHS = [
  "Quarterly Review",
  "The quarterly review covers three business units.",
  "Notwithstanding the foregoing, the parties undertook several initiatives.",
  "Headcount grew by eleven people."
];

let root: HTMLElement;
let host: DocumentHost;

function render(texts: string[]): void {
  root = document.createElement("div");
  root.innerHTML = texts
    .map((text, index) => `<p ${PARAGRAPH_ATTRIBUTE}="p${index}">${text}</p>`)
    .join("");
  document.body.replaceChildren(root);
  host = createDemoHost(root);
}

function select(index: number): void {
  const node = root.querySelectorAll("p")[index];
  const range = document.createRange();
  range.selectNodeContents(node!);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

beforeEach(() => {
  render(PARAGRAPHS);
});

describe("readDocument", () => {
  it("reads the paragraphs in document order, with their ids", async () => {
    const snapshot = await host.readDocument();

    expect(snapshot.paragraphs.map((p) => p.id)).toEqual(["p0", "p1", "p2", "p3"]);
    expect(snapshot.paragraphs.map((p) => p.text)).toEqual(PARAGRAPHS);
  });

  it("skips empty paragraphs rather than sending them as document content", async () => {
    render([...PARAGRAPHS, "   "]);

    expect((await host.readDocument()).paragraphs).toHaveLength(4);
  });
});

describe("readSelection", () => {
  it("returns nothing when nothing is selected", async () => {
    expect(await host.readSelection()).toBe("");
  });

  it("returns the text the user selected", async () => {
    select(2);

    expect(await host.readSelection()).toBe(PARAGRAPHS[2]);
  });

  it("ignores a selection made outside the document surface", async () => {
    const outside = document.createElement("p");
    outside.textContent = "text in the task pane, not the document";
    document.body.append(outside);

    const range = document.createRange();
    range.selectNodeContents(outside);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);

    expect(await host.readSelection()).toBe("");
  });

  it("notifies a listener when the selection changes, until it unsubscribes", async () => {
    const listener = vi.fn();
    const unsubscribe = host.onSelectionChange(listener);

    document.dispatchEvent(new Event("selectionchange"));
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    document.dispatchEvent(new Event("selectionchange"));
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("applyEdit", () => {
  it("replaces only the paragraph that was rewritten", async () => {
    await host.applyEdit(PARAGRAPHS[2]!, "The parties undertook several initiatives.");

    const after = (await host.readDocument()).paragraphs.map((p) => p.text);

    expect(after[2]).toBe("The parties undertook several initiatives.");
    expect(after[0]).toBe(PARAGRAPHS[0]);
    expect(after[1]).toBe(PARAGRAPHS[1]);
    expect(after[3]).toBe(PARAGRAPHS[3]);
  });

  it("leaves the document untouched until it is called", async () => {
    // The rewrite flow reads and measures; it never reaches this method. The
    // document a reader sees before pressing Apply is the document they loaded.
    expect((await host.readDocument()).paragraphs.map((p) => p.text)).toEqual(PARAGRAPHS);
  });

  it("refuses, and changes nothing, when the original text is gone", async () => {
    await expect(host.applyEdit("text that is not in the document", "new")).rejects.toBeInstanceOf(
      HostError
    );

    expect((await host.readDocument()).paragraphs.map((p) => p.text)).toEqual(PARAGRAPHS);
  });

  it("refuses, and changes nothing, when the original text is ambiguous", async () => {
    render([...PARAGRAPHS, PARAGRAPHS[2]!]);

    await expect(host.applyEdit(PARAGRAPHS[2]!, "new text")).rejects.toThrow(/appears 2 times/u);

    const after = (await host.readDocument()).paragraphs.map((p) => p.text);

    expect(after.filter((text) => text === PARAGRAPHS[2])).toHaveLength(2);
    expect(after).not.toContain("new text");
  });

  it("matches on normalised whitespace, so a re-flowed paragraph still applies", async () => {
    render(["A paragraph   with\n odd spacing."]);
    await host.applyEdit("A paragraph with odd spacing.", "Tidy.");

    expect((await host.readDocument()).paragraphs[0]!.text).toBe("Tidy.");
  });
});
