import { describe, expect, it } from "vitest";
import { groupChanges } from "@/lib/groupChanges";
import type { PendingChange } from "@/lib/types";

/**
 * Exists because of a real observed case: a document-wide styling
 * instruction ("add margin-bottom to every paragraph") came back from
 * SuperDocs as four separate pending changes, one per chunk, each with the
 * same explanation and no visible text difference. Reviewing that as four
 * decisions is not four decisions.
 */

function change(overrides: Partial<PendingChange>): PendingChange {
  return {
    change_id: "c1",
    operation: "edit",
    chunk_id: "chunk-1",
    document_id: "doc_primary",
    old_html: "<p>Hello world.</p>",
    new_html: "<p>Hello world.</p>",
    ai_explanation: "Styling update",
    ...overrides,
  };
}

describe("groupChanges", () => {
  it("collapses identical-explanation, no-op changes into one group", () => {
    const changes = [
      change({ change_id: "c1", chunk_id: "chunk-1" }),
      change({ change_id: "c2", chunk_id: "chunk-2" }),
      change({ change_id: "c3", chunk_id: "chunk-3" }),
    ];
    const groups = groupChanges(changes);
    expect(groups).toHaveLength(1);
    expect(groups[0].changeIds).toEqual(["c1", "c2", "c3"]);
  });

  it("does not group changes that carry a real text difference, even with the same explanation", () => {
    const changes = [
      change({ change_id: "c1", old_html: "<p>Hello world.</p>", new_html: "<p>Hello there, world.</p>" }),
      change({ change_id: "c2", old_html: "<p>Goodbye.</p>", new_html: "<p>Farewell.</p>" }),
    ];
    const groups = groupChanges(changes);
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.changeIds)).toEqual([["c1"], ["c2"]]);
  });

  it("keeps no-op changes with different explanations in separate groups", () => {
    const changes = [
      change({ change_id: "c1", ai_explanation: "Add margin" }),
      change({ change_id: "c2", ai_explanation: "Normalise whitespace" }),
    ];
    const groups = groupChanges(changes);
    expect(groups).toHaveLength(2);
  });

  it("passes single ungrouped changes through unchanged", () => {
    const c = change({ change_id: "c1", old_html: "<p>A.</p>", new_html: "<p>B.</p>" });
    const groups = groupChanges([c]);
    expect(groups).toEqual([{ key: "c1", explanation: c.ai_explanation, changeIds: ["c1"], sample: c }]);
  });

  it("returns nothing for an empty input", () => {
    expect(groupChanges([])).toEqual([]);
  });
});
