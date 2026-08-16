import type {
  Claim,
  Evidence,
  PaperBlock,
  PaperDocument,
  MetricConflict,
  NotebookCell,
} from "./types.js";
import { figureCaption } from "./figures.js";

export interface PaperGenerationInput {
  title: string;
  evidence: Evidence[];
  claims: Claim[];
  markdownCells?: NotebookCell[];
  conflicts?: MetricConflict[];
}

export function generatePaper(input: PaperGenerationInput): PaperDocument {
  const blocks: PaperBlock[] = [];
  const evidenceById = new Map(input.evidence.map((item) => [item.id, item]));

  for (const block of markdownBlocks(input.markdownCells ?? [])) blocks.push(block);

  blocks.push({
    id: "heading:results",
    type: "heading",
    content: "Results",
    evidenceIds: [],
    claimIds: [],
  });

  for (const conflict of input.conflicts ?? []) {
    blocks.push({
      id: `conflict:${conflict.key}`,
      type: "conflict",
      content: `Conflict detected: ${conflict.message}`,
      evidenceIds: conflict.evidenceIds,
      claimIds: [],
      metadata: { conflictKey: conflict.key, values: conflict.values },
    });
  }

  for (const claim of input.claims) {
    const sentence = buildClaimSentence(claim, evidenceById);

    blocks.push({
      id: `paragraph:${claim.id}`,
      type: "paragraph",
      content: sentence,
      evidenceIds: claim.evidenceIds,
      claimIds: [claim.id],
    });
  }

  const figureEvidence = input.evidence.filter((item) => item.kind === "figure");
  let figureNumber = 1;

  for (const figure of figureEvidence) {
    const figureId = String(figure.metadata?.figureId ?? figure.id);

    blocks.push({
      id: `figure:${figureId}`,
      type: "figure",
      content: figureCaption(
        figureNumber++,
        String(figure.metadata?.description ?? "Generated figure from notebook analysis"),
      ),
      evidenceIds: [figure.id],
      claimIds: [],
      metadata: {
        figureNumber: figureNumber - 1,
        figureEvidenceId: figure.id,
        mimeType: figure.metadata?.mimeType,
        imageBase64: figure.metadata?.imageBase64,
      },
    });
  }

  const equationEvidence = input.evidence.filter((item) => item.kind === "equation");
  for (const equation of equationEvidence) {
    blocks.push({
      id: `equation:${equation.id.replace(/^equation:/, "")}`,
      type: "equation",
      content: String(equation.value ?? ""),
      evidenceIds: [equation.id],
      claimIds: [],
      metadata: {
        latex: true,
        display: equation.metadata?.display !== false,
      },
    });
  }

  return {
    title: input.title,
    blocks,
    conflicts: input.conflicts,
  };
}

function markdownBlocks(cells: NotebookCell[]): PaperBlock[] {
  const blocks: PaperBlock[] = [];
  for (const cell of cells.filter((item) => item.cellType === "markdown")) {
    const lines = cell.source.split(/\r?\n/);
    let paragraph: string[] = [];
    let paragraphStart = 0;
    let inDisplayEquation = false;
    const flush = (endLine: number) => {
      const content = paragraph.join(" ").trim();
      if (content) {
        blocks.push({
          id: `markdown:${cell.id}:paragraph:${paragraphStart + 1}`,
          type: "paragraph",
          content: content.replace(/\$\$[\s\S]*?\$\$/g, "").replace(/\s+/g, " ").trim(),
          evidenceIds: [],
          claimIds: [],
          metadata: { sourceCellId: cell.id, sourceLineStart: paragraphStart + 1, sourceLineEnd: endLine },
        });
      }
      paragraph = [];
    };

    lines.forEach((line, index) => {
      const trimmed = line.trim();
      if (/^\$\$/.test(trimmed)) {
        flush(index);
        inDisplayEquation = !inDisplayEquation;
        paragraphStart = index + 1;
        return;
      }
      if (inDisplayEquation) return;
      if (/^#\s+/.test(trimmed) && index === 0) return;
      const heading = trimmed.match(/^(#{2,6})\s+(.+)$/);
      if (heading) {
        flush(index);
        blocks.push({
          id: `markdown:${cell.id}:heading:${index + 1}`,
          type: "heading",
          content: heading[2].trim(),
          evidenceIds: [],
          claimIds: [],
          metadata: { sourceCellId: cell.id, sourceLineStart: index + 1, sourceLineEnd: index + 1 },
        });
        paragraphStart = index + 1;
        return;
      }
      if (!trimmed) {
        flush(index);
        paragraphStart = index + 1;
        return;
      }
      if (paragraph.length === 0) paragraphStart = index;
      paragraph.push(trimmed);
    });
    flush(lines.length - 1);
  }
  return blocks;
}

function buildClaimSentence(
  claim: Claim,
  evidenceById: Map<string, Evidence>,
): string {
  const values = claim.evidenceIds
    .map((id) => evidenceById.get(id))
    .filter((item): item is Evidence => Boolean(item));

  const metrics = values.filter((item) => item.kind === "metric");
  if (metrics.length >= 2) {
    const rendered = metrics
      .slice(0, 2)
      .map((item) => `${item.label} was ${formatValue(item.value, item.unit)}`)
      .join(", while ");

    return `${claim.statement} ${rendered}.`;
  }

  const statistics = values.filter((item) => item.kind === "statistic");
  if (statistics.length > 0) {
    return `${claim.statement} The reported statistical result was ${formatValue(statistics[0].value)}.`;
  }

  return `${claim.statement}`;
}

function formatValue(value: unknown, unit?: string): string {
  if (typeof value === "number" && unit === "percent") {
    return `${value.toFixed(1)}%`;
  }
  if (typeof value === "number") {
    return value.toString();
  }
  return String(value ?? "not reported");
}
