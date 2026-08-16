import { describe, expect, it } from "vitest";
import { diffEvidence, createSnapshot, mergeIncrementalPaper } from "../src/incremental.js";
import { makeEvidence } from "../src/evidence.js";

describe("incremental diff", () => {
  it("finds a changed evidence item and affected paper block", () => {
    const base = {
      id: "metric:model_b_accuracy",
      kind: "metric" as const,
      source: { notebook: "n.ipynb", cellId: "metrics", cellIndex: 1 },
      label: "Model B accuracy",
      value: 0.881,
    };

    const changed = {
      ...base,
      value: 0.914,
    };

    const beforeEvidence = [makeEvidence(base)];
    const afterEvidence = [makeEvidence(changed)];

    const paper = {
      title: "Results",
      blocks: [
        {
          id: "paragraph:accuracy",
          type: "paragraph" as const,
          content: "Model B outperformed Model A.",
          evidenceIds: ["metric:model_b_accuracy"],
          claimIds: [],
        },
        {
          id: "paragraph:unrelated",
          type: "paragraph" as const,
          content: "Unrelated background.",
          evidenceIds: ["metric:other"],
          claimIds: [],
        },
      ],
    };

    const diff = diffEvidence(
      createSnapshot("v1", "n.ipynb", beforeEvidence),
      createSnapshot("v2", "n.ipynb", afterEvidence),
      paper,
    );

    expect(diff.affectedEvidenceIds).toEqual(["metric:model_b_accuracy"]);
    expect(diff.affectedBlockIds).toEqual(["paragraph:accuracy"]);
  });

  it("reuses unaffected blocks during regeneration", () => {
    const previous = {
      title: "Results",
      blocks: [
        { id: "heading", type: "heading" as const, content: "Results", evidenceIds: [], claimIds: [] },
        { id: "changed", type: "paragraph" as const, content: "old", evidenceIds: ["e1"], claimIds: [] },
        { id: "untouched", type: "paragraph" as const, content: "exactly unchanged", evidenceIds: ["e2"], claimIds: [] },
      ],
    };
    const regenerated = {
      title: "Results",
      blocks: [
        { id: "heading", type: "heading" as const, content: "Results", evidenceIds: [], claimIds: [] },
        { id: "changed", type: "paragraph" as const, content: "new", evidenceIds: ["e1"], claimIds: [] },
        { id: "untouched", type: "paragraph" as const, content: "rewritten accidentally", evidenceIds: ["e2"], claimIds: [] },
      ],
    };

    const merged = mergeIncrementalPaper(previous, regenerated, ["changed"]);
    expect(merged.blocks[1]?.content).toBe("new");
    expect(merged.blocks[2]).toBe(previous.blocks[2]);
  });
});
