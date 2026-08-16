import type { Evidence, NotebookDocument } from "./types.js";
import { extractEquationEvidence, extractMetricEvidence } from "./evidence.js";
import { createFigureEvidence, extractFigureArtifacts } from "./figures.js";

export function notebookToEvidence(notebook: NotebookDocument): Evidence[] {
  const result: Evidence[] = [];

  for (const cell of notebook.cells) {
    result.push(...extractMetricEvidence(notebook, cell));
    result.push(...extractEquationEvidence(notebook, cell));

    for (const artifact of extractFigureArtifacts(notebook, cell)) {
      result.push(createFigureEvidence(notebook, cell, artifact));
    }
  }

  const map = new Map<string, Evidence>();
  for (const item of result) {
    map.set(item.id, item);
  }
  return [...map.values()];
}
