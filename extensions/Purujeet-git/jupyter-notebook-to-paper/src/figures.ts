import { sha256 } from "./hashing.js";
import { makeEvidence, createSourceRef } from "./evidence.js";
import type { Evidence, FigureArtifact, NotebookCell, NotebookDocument } from "./types.js";

const IMAGE_MIME_TYPES = ["image/png", "image/jpeg", "image/svg+xml", "image/webp"];

export function extractFigureArtifacts(
  notebook: NotebookDocument,
  cell: NotebookCell,
): FigureArtifact[] {
  const figures: FigureArtifact[] = [];

  for (const [outputIndex, output] of cell.outputs.entries()) {
    if (output.outputType !== "display_data" && output.outputType !== "execute_result") {
      continue;
    }

    for (const mimeType of IMAGE_MIME_TYPES) {
      const raw = output.data?.[mimeType];
      if (typeof raw !== "string" && !Array.isArray(raw)) continue;

      const imageBase64 = Array.isArray(raw) ? raw.join("") : raw;
      const hash = sha256(imageBase64);

      figures.push({
        evidenceId: `figure:${hash.slice(0, 16)}`,
        figureId: `fig:${hash.slice(0, 16)}`,
        imageBase64,
        mimeType,
        hash,
        outputIndex,
      });
    }
  }

  return figures;
}

export function createFigureEvidence(
  notebook: NotebookDocument,
  cell: NotebookCell,
  artifact: FigureArtifact,
): Evidence {
  return makeEvidence({
    id: artifact.evidenceId,
    kind: "figure",
    source: createSourceRef(notebook, cell, { outputIndex: artifact.outputIndex }),
    label: "Generated figure",
    value: artifact.hash,
    metadata: {
      figureId: artifact.figureId,
      mimeType: artifact.mimeType,
      imageBase64: artifact.imageBase64,
      description: figureDescription(cell),
    },
  });
}

function figureDescription(cell: NotebookCell): string {
  const title = cell.source.match(/(?:title|set_title)\s*\(\s*["']([^"']+)["']/i)?.[1];
  if (title) return title;

  const plainText = cell.outputs
    .map((output) => output.data?.["text/plain"] ?? output.text)
    .find((value): value is string => typeof value === "string");
  return plainText?.replace(/<[^>]+>/g, "").trim() || "Figure generated from notebook analysis";
}

export function figureCaption(
  figureNumber: number,
  description: string,
): string {
  return `Figure ${figureNumber}. ${description}`;
}
