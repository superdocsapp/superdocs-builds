import { sha256, stableJson } from "./hashing.js";
import type {
  Claim,
  Evidence,
  EvidenceKind,
  NotebookCell,
  NotebookDocument,
  PaperBlock,
  PaperDocument,
  SourceRef,
} from "./types.js";

const METRIC_PATTERN =
  /^([A-Za-z][A-Za-z0-9 _-]*?):?\s*((?:[-+]?\d+(?:\.\d+)?)(?:%|[eE][-+]?\d+)?)[ \t]*$/i;

const LABELED_NUMBER_PATTERN =
  /^([^:]+):\s*([-+]?\d+(?:\.\d+)?(?:%|[eE][-+]?\d+)?)\s*$/;

const INLINE_LATEX_PATTERN = /\$([^$\n]+)\$/g;
const DISPLAY_LATEX_PATTERN = /\$\$([\s\S]*?)\$\$/g;

export function createSourceRef(
  notebook: NotebookDocument,
  cell: NotebookCell,
  range: Partial<SourceRef> = {},
): SourceRef {
  return {
    notebook: notebook.path,
    cellId: cell.id,
    cellIndex: cell.index,
    ...range,
  };
}

export function makeEvidence(
  input: Omit<Evidence, "fingerprint">,
): Evidence {
  const withoutFingerprint = {
    id: input.id,
    kind: input.kind,
    source: input.source,
    label: input.label,
    value: input.value,
    unit: input.unit,
    metadata: input.metadata ?? {},
  };
  return {
    ...input,
    metadata: input.metadata ?? {},
    fingerprint: sha256(stableJson(withoutFingerprint)),
  };
}

export function extractTextOutputs(cell: NotebookCell): string[] {
  return cell.outputs
    .filter((output) => output.outputType === "stream" || output.outputType === "execute_result" || output.outputType === "display_data")
    .map((output) => {
      const text = output.text;
      if (text) return text;
      const plain = output.data?.["text/plain"];
      return normalizeDataText(plain);
    })
    .filter((value): value is string => Boolean(value));
}

export function extractMetricEvidence(
  notebook: NotebookDocument,
  cell: NotebookCell,
): Evidence[] {
  const evidence: Evidence[] = [];

  for (const [outputIndex, text] of extractTextOutputsWithIndexes(cell)) {
    let offset = 0;
    const lines = text.split(/\r?\n/);
    for (const [lineIndex, line] of lines.entries()) {
      const clean = line.trim();
      const lineStart = offset;
      const lineEnd = offset + line.length;
      offset += line.length + 1;
      if (!clean) continue;

      const match = clean.match(LABELED_NUMBER_PATTERN);
      if (!match) continue;

      const label = match[1].trim();
      const rawValue = match[2].trim();
      const unit = rawValue.endsWith("%") ? "percent" : undefined;
      const numericValue = Number(rawValue.replace(/%$/, ""));

      const id = `${isStatisticLabel(label) ? "statistic" : "metric"}:${slug(label)}:${cell.id}`;
      evidence.push(
        makeEvidence({
          id,
          kind: isStatisticLabel(label) ? "statistic" : "metric",
          source: createSourceRef(notebook, cell, {
            outputIndex,
            outputLineStart: lineIndex + 1,
            outputLineEnd: lineIndex + 1,
            outputCharStart: lineStart,
            outputCharEnd: lineEnd,
          }),
          label,
          value: numericValue,
          unit,
          metadata: { raw: rawValue },
        }),
      );
    }
  }

  return dedupeEvidence(evidence);
}

export function extractEquationEvidence(
  notebook: NotebookDocument,
  cell: NotebookCell,
): Evidence[] {
  if (cell.cellType !== "markdown") return [];

  const equations: Evidence[] = [];
  const source = cell.source;

  for (const match of source.matchAll(DISPLAY_LATEX_PATTERN)) {
    const latex = match[1].trim();
    if (!latex) continue;

    const id = `equation:${sha256(latex).slice(0, 12)}`;
    equations.push(
      makeEvidence({
        id,
        kind: "equation",
        source: createSourceRef(notebook, cell, sourceRange(source, match.index ?? 0, match[0].length)),
        label: "Mathematical expression",
        value: latex,
        metadata: { display: true },
      }),
    );
  }

  for (const match of source.matchAll(INLINE_LATEX_PATTERN)) {
    const latex = match[1].trim();
    if (!latex) continue;

    const id = `equation:${sha256(latex).slice(0, 12)}`;
    if (equations.some((item) => item.id === id)) continue;

    equations.push(
      makeEvidence({
        id,
        kind: "equation",
        source: createSourceRef(notebook, cell, sourceRange(source, match.index ?? 0, match[0].length)),
        label: "Mathematical expression",
        value: latex,
        metadata: { display: false },
      }),
    );
  }

  return equations;
}

export function createClaim(
  id: string,
  statement: string,
  evidenceIds: string[],
): Claim {
  return { id, statement, evidenceIds };
}

export function createPaperDocument(
  title: string,
  blocks: PaperBlock[],
): PaperDocument {
  return { title, blocks };
}

export function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/%/g, "percent")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function normalizeDataText(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (Array.isArray(value)) return value.join("");
  if (typeof value === "string") return value;
  return String(value);
}

function extractTextOutputsWithIndexes(cell: NotebookCell): Array<[number, string]> {
  return cell.outputs
    .map((output, index): [number, string | undefined] => {
      if (output.outputType !== "stream" && output.outputType !== "execute_result" && output.outputType !== "display_data") {
        return [index, undefined];
      }
      const text = output.text || normalizeDataText(output.data?.["text/plain"]);
      return [index, text];
    })
    .filter((item): item is [number, string] => Boolean(item[1]));
}

function sourceRange(source: string, start: number, length: number): Partial<SourceRef> {
  const before = source.slice(0, start);
  const value = source.slice(start, start + length);
  const lineStart = before.split(/\r?\n/).length;
  const lineEnd = lineStart + value.split(/\r?\n/).length - 1;
  const lastLineStart = Math.max(before.lastIndexOf("\n"), before.lastIndexOf("\r")) + 1;
  return {
    sourceLineStart: lineStart,
    sourceLineEnd: lineEnd,
    sourceCharStart: start,
    sourceCharEnd: start + length,
  };
}

function dedupeEvidence(items: Evidence[]): Evidence[] {
  const map = new Map<string, Evidence>();
  for (const item of items) map.set(item.id, item);
  return [...map.values()];
}

export function evidenceKindLabel(kind: EvidenceKind): string {
  return kind;
}

function isStatisticLabel(label: string): boolean {
  return /\b(p[- ]?value|t[- ]?test|chi[- ]?square|anova|confidence interval|correlation|r\s*value)\b/i.test(label);
}
