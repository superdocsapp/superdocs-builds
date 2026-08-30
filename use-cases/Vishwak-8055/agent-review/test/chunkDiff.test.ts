import { describe, expect, it } from "vitest";
import { diffChunkMaps, diffDocumentHtml, canSafelyRoundTrip, DuplicateChunkIdError, parseChunks, serializeChunks } from "../src/chunkDiff";

describe("parseChunks", () => {
  it("extracts flat top-level chunks in document order", () => {
    const html =
      '<h1 data-chunk-id="c-title">Project Proposal</h1>' +
      '<p data-chunk-id="c-para1">Original paragraph text.</p>';
    const chunks = parseChunks(html);
    expect([...chunks.keys()]).toEqual(["c-title", "c-para1"]);
    expect(chunks.get("c-title")).toBe('<h1 data-chunk-id="c-title">Project Proposal</h1>');
    expect(chunks.get("c-para1")).toBe(
      '<p data-chunk-id="c-para1">Original paragraph text.</p>'
    );
  });

  it("treats nested chunk ids (e.g. table > tr > td) as part of their top-level parent, not separate entries", () => {
    const html =
      '<table data-chunk-id="c-table">' +
      '<tr data-chunk-id="c-row1"><td data-chunk-id="c-cell1">A</td></tr>' +
      "</table>";
    const chunks = parseChunks(html);
    // Only the top-level chunk is a map entry — this is what makes
    // serializeChunks safe (see the document-integrity tests below).
    expect([...chunks.keys()]).toEqual(["c-table"]);
    expect(chunks.get("c-table")).toBe(html);
  });

  it("does not lose content when two sibling chunks share a tag name", () => {
    const html =
      '<p data-chunk-id="a">First</p>' +
      '<p data-chunk-id="b">Second</p>' +
      '<p data-chunk-id="c">Third</p>';
    const chunks = parseChunks(html);
    expect(chunks.get("a")).toBe('<p data-chunk-id="a">First</p>');
    expect(chunks.get("b")).toBe('<p data-chunk-id="b">Second</p>');
    expect(chunks.get("c")).toBe('<p data-chunk-id="c">Third</p>');
  });

  it("returns an empty map for HTML with no chunk ids", () => {
    expect(parseChunks("<p>no chunk id here</p>").size).toBe(0);
  });
});

describe("diffChunkMaps", () => {
  it("reports no entries for identical snapshots", () => {
    const before = parseChunks('<p data-chunk-id="a">same</p>');
    const after = parseChunks('<p data-chunk-id="a">same</p>');
    expect(diffChunkMaps(before, after)).toEqual([]);
  });

  it("detects an edit", () => {
    const before = parseChunks('<p data-chunk-id="a">old text</p>');
    const after = parseChunks('<p data-chunk-id="a">new text</p>');
    const diff = diffChunkMaps(before, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]).toMatchObject({
      chunkId: "a",
      operation: "edit",
      beforeHtml: '<p data-chunk-id="a">old text</p>',
      afterHtml: '<p data-chunk-id="a">new text</p>',
    });
  });

  it("detects a create and anchors it to the nearest surviving predecessor", () => {
    const before = parseChunks('<p data-chunk-id="a">A</p><p data-chunk-id="c">C</p>');
    const after = parseChunks(
      '<p data-chunk-id="a">A</p><p data-chunk-id="b">B</p><p data-chunk-id="c">C</p>'
    );
    const diff = diffChunkMaps(before, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]).toMatchObject({
      chunkId: "b",
      operation: "create",
      beforeHtml: null,
      insertAfterChunkId: "a",
    });
  });

  it("detects a delete and anchors it to the nearest surviving predecessor", () => {
    const before = parseChunks(
      '<p data-chunk-id="a">A</p><p data-chunk-id="b">B</p><p data-chunk-id="c">C</p>'
    );
    const after = parseChunks('<p data-chunk-id="a">A</p><p data-chunk-id="c">C</p>');
    const diff = diffChunkMaps(before, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]).toMatchObject({
      chunkId: "b",
      operation: "delete",
      afterHtml: null,
      insertAfterChunkId: "a",
    });
  });

  it("reports independent edits to two different chunks as two separate entries", () => {
    const before = parseChunks(
      '<h1 data-chunk-id="title">Old Title</h1><p data-chunk-id="para">Old para.</p>'
    );
    const after = parseChunks(
      '<h1 data-chunk-id="title">New Title</h1><p data-chunk-id="para">New para.</p>'
    );
    const diff = diffChunkMaps(before, after);
    expect(diff.map((d) => d.chunkId).sort()).toEqual(["para", "title"]);
    expect(diff.every((d) => d.operation === "edit")).toBe(true);
  });
});

describe("serializeChunks", () => {
  it("round-trips parseChunks -> serializeChunks back to the original HTML", () => {
    const html = '<h1 data-chunk-id="a">Title</h1><p data-chunk-id="b">Body.</p>';
    expect(serializeChunks(parseChunks(html))).toBe(html);
  });

  it("reflects patches applied to the map (used to write a revert back to SuperDocs)", () => {
    const chunks = parseChunks('<p data-chunk-id="a">old</p><p data-chunk-id="b">keep</p>');
    chunks.set("a", '<p data-chunk-id="a">restored</p>');
    expect(serializeChunks(chunks)).toBe('<p data-chunk-id="a">restored</p><p data-chunk-id="b">keep</p>');
  });
});

describe("duplicate chunk ids — never silently produce a misleading diff", () => {
  it("throws DuplicateChunkIdError rather than silently dropping one occurrence", () => {
    const before = '<p data-chunk-id="a">first</p><p data-chunk-id="a">duplicate</p>';
    const after = '<p data-chunk-id="a">changed</p>';
    expect(() => diffDocumentHtml(before, after)).toThrow(DuplicateChunkIdError);
  });

  it("reports which id(s) were duplicated", () => {
    const before = '<p data-chunk-id="x">1</p><p data-chunk-id="x">2</p>';
    try {
      diffDocumentHtml(before, "<p>ok</p>");
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(DuplicateChunkIdError);
      expect((err as InstanceType<typeof DuplicateChunkIdError>).duplicateIds).toEqual(["x"]);
    }
  });

  it("does not flag a normal document with no duplicates", () => {
    expect(() => diffDocumentHtml('<p data-chunk-id="a">1</p>', '<p data-chunk-id="a">2</p>')).not.toThrow();
  });

  it("a document with a duplicate id also fails canSafelyRoundTrip (belt-and-suspenders for the write-back gate)", () => {
    const html = '<p data-chunk-id="a">first</p><p data-chunk-id="a">second</p>';
    expect(canSafelyRoundTrip(html)).toBe(false);
  });
});

describe("document integrity — nested/tabular content must not be duplicated on round-trip", () => {
  it("a table with chunked rows and cells round-trips byte-for-byte, not duplicated", () => {
    const html =
      '<table data-chunk-id="t1">' +
      '<tr data-chunk-id="r1"><td data-chunk-id="c1">A1</td><td data-chunk-id="c2">B1</td></tr>' +
      '<tr data-chunk-id="r2"><td data-chunk-id="c3">A2</td><td data-chunk-id="c4">B2</td></tr>' +
      "</table>";
    expect(serializeChunks(parseChunks(html))).toBe(html);
    // The specific corruption this guards against: cell content appearing twice.
    const serialized = serializeChunks(parseChunks(html));
    expect(serialized.match(/A1/g)?.length).toBe(1);
  });

  it("editing a table is captured as one edit to the table chunk, not overlapping edits to its rows/cells", () => {
    const before = '<table data-chunk-id="t1"><tr data-chunk-id="r1"><td data-chunk-id="c1">A</td></tr></table>';
    const after = '<table data-chunk-id="t1"><tr data-chunk-id="r1"><td data-chunk-id="c1">B</td></tr></table>';
    const diff = diffDocumentHtml(before, after);
    expect(diff).toHaveLength(1);
    expect(diff[0]?.chunkId).toBe("t1");
  });

  it("content around/between chunks that our model does not capture makes canSafelyRoundTrip false", () => {
    // A wrapper this model doesn't account for — round trip must NOT claim safety.
    const html = '<div class="doc-wrapper"><p data-chunk-id="a">only chunk</p></div>';
    expect(canSafelyRoundTrip(html)).toBe(false);
  });

  it("a document that is exactly a flat sequence of top-level chunks is provably safe to round-trip", () => {
    const html = '<h1 data-chunk-id="a">Title</h1><p data-chunk-id="b">Body</p>';
    expect(canSafelyRoundTrip(html)).toBe(true);
  });
});

describe("diffDocumentHtml", () => {
  it("is equivalent to parsing both snapshots then diffing", () => {
    const beforeHtml = '<p data-chunk-id="a">old</p>';
    const afterHtml = '<p data-chunk-id="a">new</p>';
    expect(diffDocumentHtml(beforeHtml, afterHtml)).toEqual(
      diffChunkMaps(parseChunks(beforeHtml), parseChunks(afterHtml))
    );
  });
});
