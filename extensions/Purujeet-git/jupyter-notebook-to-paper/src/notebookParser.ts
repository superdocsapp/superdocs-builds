import { promises as fs } from "node:fs";
import path from "node:path";
import type { NotebookCell, NotebookDocument, NotebookOutput } from "./types.js";

interface RawNotebookCell {
  id?: string;
  cell_type?: string;
  source?: string | string[];
  outputs?: Array<Record<string, unknown>>;
  metadata?: Record<string, unknown>;
}

interface RawNotebook {
  cells?: RawNotebookCell[];
  metadata?: Record<string, unknown>;
  nbformat?: number;
  nbformat_minor?: number;
}

export class NotebookParser {
  async parse(filePath: string): Promise<NotebookDocument> {
    const absolutePath = path.resolve(filePath);

    let rawText: string;
    try {
      rawText = await fs.readFile(absolutePath, "utf8");
    } catch (error) {
      throw new Error(`Unable to read notebook: ${absolutePath}`, { cause: error });
    }

    let notebook: RawNotebook;
    try {
      notebook = JSON.parse(rawText) as RawNotebook;
    } catch (error) {
      throw new Error(`Notebook is not valid JSON: ${absolutePath}`, { cause: error });
    }

    if (!Array.isArray(notebook.cells)) {
      throw new Error(`Notebook does not contain a valid "cells" array: ${absolutePath}`);
    }

    const cells: NotebookCell[] = notebook.cells.map((cell, index) => {
      const cellType = cell.cell_type;
      if (cellType !== "code" && cellType !== "markdown" && cellType !== "raw") {
        throw new Error(`Unsupported cell_type at index ${index}: ${String(cellType)}`);
      }

      return {
        id: cell.id?.trim() || `cell-${index + 1}`,
        index,
        cellType,
        source: this.normalizeSource(cell.source ?? ""),
        outputs: (cell.outputs ?? []).map((output) => this.normalizeOutput(output)),
        metadata: { ...(cell.metadata ?? {}) },
      };
    });

    return {
      path: absolutePath,
      metadata: { ...(notebook.metadata ?? {}) },
      cells,
    };
  }

  private normalizeSource(source: string | string[]): string {
    return Array.isArray(source) ? source.join("") : source;
  }

  private normalizeOutput(output: Record<string, unknown>): NotebookOutput {
    const data = isRecord(output.data) ? { ...output.data } : undefined;
    return {
      outputType: String(output.output_type ?? "unknown"),
      text: normalizeText(output.text),
      html: normalizeText(output.html),
      data,
      metadata: isRecord(output.metadata) ? { ...output.metadata } : undefined,
      executionCount: typeof output.execution_count === "number"
        ? output.execution_count
        : null,
    };
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeText(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (Array.isArray(value)) return value.join("");
  if (typeof value === "string") return value;
  return String(value);
}

export async function loadNotebook(filePath: string): Promise<NotebookDocument> {
  return new NotebookParser().parse(filePath);
}
