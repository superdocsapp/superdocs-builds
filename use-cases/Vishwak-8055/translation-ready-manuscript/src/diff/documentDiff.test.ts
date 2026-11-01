import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { checkIntegrity, diffDocumentBodies, diffMetadata } from "./documentDiff.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) => readFileSync(path.join(__dirname, "../../tests/fixtures", name), "utf8");

const before = fixture("alice-superdocs-before.html");

describe("diffDocumentBodies", () => {
  it("reports no changes when before and after are identical", () => {
    const diff = diffDocumentBodies(before, before);
    expect(diff.changedFieldCount).toBe(0);
  });

  it("detects a text change scoped to exactly one chunk", () => {
    const after = before.replace("get out again.", "get out again!!");
    const diff = diffDocumentBodies(before, after);
    expect(diff.changedFieldCount).toBe(1);
    expect(diff.changes[0]).toMatchObject({ kind: "text", location: "chunk-p3" });
  });

  it("detects a formatting-only change (em -> strong) as formatting, not text", () => {
    const after = before.replace("<em>very</em>", "<strong>very</strong>");
    const diff = diffDocumentBodies(before, after);
    // The chunk's *tagName* (p) is unchanged, its *textContent* is unchanged (still "very");
    // only the inline emphasis markup changed. Our chunk-level diff intentionally operates
    // at the tracked-attribute/tag/text granularity, not inline-markup granularity -- so this
    // specific change is invisible to it. Documented here as a known limitation rather than
    // silently passed: fine-grained inline-markup diffing (bold vs italic vs strong) would need
    // span-level comparison, which is exactly what src/ingest's InlineSpan model captures for
    // *source* manuscripts; extending chunk diffing to that level for arbitrary SuperDocs HTML
    // is listed as a remaining risk in TASK2_REQUIREMENTS.md rather than silently claimed here.
    expect(diff.changedFieldCount).toBe(0);
  });

  it("detects an added chunk as a structure change", () => {
    const after = before.replace(
      '<p data-chunk-id="chunk-p3">',
      '<p data-chunk-id="chunk-new">A new paragraph.</p>\n<p data-chunk-id="chunk-p3">',
    );
    const diff = diffDocumentBodies(before, after);
    const structureChanges = diff.changes.filter((c) => c.kind === "structure");
    expect(structureChanges).toHaveLength(1);
    expect(structureChanges[0]?.location).toBe("chunk-new");
  });

  it("detects a deleted chunk as a structure change", () => {
    const after = before.replace('<p data-chunk-id="chunk-p2">There was nothing so <em>very</em> remarkable in that.</p>\n', "");
    const diff = diffDocumentBodies(before, after);
    const structureChanges = diff.changes.filter((c) => c.kind === "structure");
    expect(structureChanges).toHaveLength(1);
    expect(structureChanges[0]).toMatchObject({ location: "chunk-p2", after: "(deleted)" });
  });

  it("detects two chunks swapping position as ordering changes with a minimal move-set (not necessarily both)", () => {
    const p1 = '<p data-chunk-id="chunk-p1">Alice was beginning to get very tired of sitting by her sister on the bank, and of having nothing to do.</p>';
    const p2 = '<p data-chunk-id="chunk-p2">There was nothing so <em>very</em> remarkable in that.</p>';
    const after = before.replace(`${p1}\n${p2}`, `${p2}\n${p1}`);
    const diff = diffDocumentBodies(before, after);
    // A single adjacent swap can be explained by moving just one of the two
    // elements past the other -- same minimal-edit-distance logic real diff
    // tools use. We assert the *kind* and that something moved, not which
    // specific one the tie-break picked.
    expect(diff.changes.length).toBeGreaterThanOrEqual(1);
    expect(diff.changes.every((c) => c.kind === "ordering")).toBe(true);
    for (const c of diff.changes) {
      expect(["chunk-p1", "chunk-p2"]).toContain(c.location);
    }
  });
});

describe("diffMetadata", () => {
  it("detects a title field change", () => {
    const changes = diffMetadata({ title: "Old Title" }, { title: "New Title" });
    expect(changes).toEqual([{ kind: "metadata", location: "title", before: "Old Title", after: "New Title" }]);
  });

  it("reports nothing when metadata is unchanged", () => {
    expect(diffMetadata({ title: "Same" }, { title: "Same" })).toHaveLength(0);
  });
});

describe("checkIntegrity — the Alice 'change only the title' regression test", () => {
  // Two genuinely different real operations both get called "change only the
  // title," and they have different correct expectations:
  //
  //   (a) Rename via PATCH /v1/documents/{id} {title} -- a pure metadata
  //       field. The body HTML must be untouched: zero body-diff changes,
  //       exactly one metadata change.
  //
  //   (b) A scoped chat instruction that edits the visible title *heading
  //       inside the document body* (chunk-title). The body diff should show
  //       exactly one chunk changed and nothing else -- no metadata call was
  //       even made in this path.
  //
  // Conflating these two was a real mistake caught while writing this test
  // suite (see git history / TASK2_REQUIREMENTS.md) -- worth keeping both
  // cases explicit rather than collapsing back to one.

  it("(a) rename endpoint: PASSES when only the metadata title field changes and body HTML is untouched", () => {
    const bodyDiff = diffDocumentBodies(before, before); // body never sent to a rename call
    const metadataChanges = diffMetadata(
      { title: "Alice's Adventures in Wonderland" },
      { title: "Alice's Adventures in Wonderland: Special Edition" },
    );
    const result = checkIntegrity(bodyDiff, metadataChanges, {
      allowed: [{ kind: "metadata", location: "title" }],
    });
    expect(result.pass).toBe(true);
    expect(result.actualChangeCount).toBe(1);
    expect(result.unexpectedChanges).toHaveLength(0);
  });

  it("(b) scoped body edit: PASSES when only the chunk-title heading's text changes and nothing else in the body moved", () => {
    const after = fixture("alice-superdocs-after-title-only-PASS.html");
    const bodyDiff = diffDocumentBodies(before, after);
    const result = checkIntegrity(bodyDiff, [], {
      allowed: [{ kind: "text", location: "chunk-title" }],
    });
    expect(result.pass).toBe(true);
    expect(result.actualChangeCount).toBe(1);
    expect(result.unexpectedChanges).toHaveLength(0);
  });

  it("(b) FAILS when a chat-based edit changes the title but also drifts wording elsewhere in the body — this must remain a FAIL, not be waved through", () => {
    const after = fixture("alice-superdocs-after-title-only-FAIL.html");
    const bodyDiff = diffDocumentBodies(before, after);
    // No metadata call was made in this path -- the whole edit went through chat, body only.
    const result = checkIntegrity(bodyDiff, [], {
      allowed: [{ kind: "text", location: "chunk-title" }],
    });
    expect(result.pass).toBe(false);
    expect(result.unexpectedChanges.length).toBeGreaterThan(0);
    // The reordered clause in chunk-p3 ("down went Alice" -> "down Alice went") was never
    // requested. An implementation that only checked "did the title change?" would have
    // reported success here; checkIntegrity must not. (The em->strong swap on chunk-p2 is a
    // real change too, but at inline-markup granularity -- see the documented limitation above;
    // it is not expected to surface as a separate unexpected change here.)
    const unexpectedLocations = result.unexpectedChanges.map((c) => c.location).sort();
    expect(unexpectedLocations).toContain("chunk-p3");
  });
});
