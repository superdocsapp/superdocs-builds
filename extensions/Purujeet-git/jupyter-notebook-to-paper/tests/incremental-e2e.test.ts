import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { loadNotebook } from "../src/notebookParser.js";
import { notebookToEvidence } from "../src/notebookToEvidence.js";
import { buildClaimsFromEvidence } from "../src/prose.js";
import { generatePaper } from "../src/paperGenerator.js";
import { detectMetricConflicts } from "../src/conflicts.js";
import { createSnapshot, diffEvidence, mergeIncrementalPaper } from "../src/incremental.js";

function notebookJson(modelBAccuracy: string): string {
  return JSON.stringify({
    nbformat: 4,
    nbformat_minor: 5,
    metadata: {},
    cells: [
      {
        id: "title-and-intro",
        cell_type: "markdown",
        source: "# Incremental Study\n\nThis introduction must remain unchanged across updates.\n\n## Methods\n\nWe compare two models on the same held-out dataset.",
        metadata: {},
      },
      {
        id: "metrics",
        cell_type: "code",
        source: "print('metrics')",
        execution_count: 1,
        metadata: {},
        outputs: [{
          output_type: "stream",
          name: "stdout",
          text: `Model A accuracy: 0.881\nModel B accuracy: ${modelBAccuracy}\n`,
        }],
      },
      {
        id: "discussion",
        cell_type: "markdown",
        source: "## Discussion\n\nThis discussion is unrelated to the changed metric and must remain unchanged.",
        metadata: {},
      },
    ],
  }, null, 2);
}

async function buildPaper(notebookPath: string) {
  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const claims = buildClaimsFromEvidence(evidence, conflicts);
  return {
    notebook,
    evidence,
    paper: generatePaper({
      title: "Incremental Study",
      evidence,
      claims,
      markdownCells: notebook.cells,
      conflicts,
    }),
  };
}

describe("incremental notebook update end to end", () => {
  it("updates only the affected result prose across two actual notebook versions", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-paper-two-versions-"));
    // A real update keeps the notebook path stable while its contents change.
    const notebookPath = path.join(directory, "study.ipynb");
    await fs.writeFile(notebookPath, notebookJson("0.902"), "utf8");

    const before = await buildPaper(notebookPath);
    await fs.writeFile(notebookPath, notebookJson("0.944"), "utf8");
    const after = await buildPaper(notebookPath);
    const beforeSnapshot = createSnapshot("v1", before.notebook.path, before.evidence);
    const afterSnapshot = createSnapshot("v2", after.notebook.path, after.evidence);
    const diff = diffEvidence(beforeSnapshot, afterSnapshot, before.paper);
    const merged = mergeIncrementalPaper(before.paper, after.paper, diff.affectedBlockIds);

    expect(diff.changes).toHaveLength(1);
    expect(diff.changes[0]).toMatchObject({
      evidenceId: "metric:model-b-accuracy:metrics",
      kind: "changed",
      before: { value: 0.902 },
      after: { value: 0.944 },
    });

    const changedBlockId = "paragraph:claim:comparison:accuracy";
    expect(diff.affectedBlockIds).toEqual([changedBlockId]);

    const beforeById = new Map(before.paper.blocks.map((block) => [block.id, block]));
    const afterById = new Map(merged.blocks.map((block) => [block.id, block]));
    const unchangedIds = before.paper.blocks
      .map((block) => block.id)
      .filter((id) => id !== changedBlockId);

    for (const id of unchangedIds) {
      expect(afterById.get(id)).toEqual(beforeById.get(id));
    }

    expect(afterById.get(changedBlockId)?.content).toContain("0.944");
    expect(afterById.get(changedBlockId)?.content).not.toEqual(beforeById.get(changedBlockId)?.content);
  });
});
