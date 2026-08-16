import { describe, expect, it } from "vitest";
import { loadNotebook } from "../src/notebookParser.js";
import { notebookToEvidence } from "../src/notebookToEvidence.js";
import { buildClaimsFromEvidence } from "../src/prose.js";
import { generatePaper } from "../src/paperGenerator.js";
import { renderMarkdown } from "../src/markdown.js";
import { renderHtml } from "../src/html.js";
import { detectMetricConflicts } from "../src/conflicts.js";
import { makeEvidence } from "../src/evidence.js";

describe("paper pipeline", () => {
  it("extracts statistics and preserves figure data and captions", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    const evidence = notebookToEvidence(notebook);
    const statistic = evidence.find((item) => item.kind === "statistic");
    const figure = evidence.find((item) => item.kind === "figure");

    expect(statistic?.label).toContain("p-value");
    expect(figure?.metadata?.imageBase64).toBeTypeOf("string");
    expect(figure?.metadata?.description).toBe("Synthetic Model Accuracy Comparison");
  });

  it("makes comparison claims from values instead of fixed model names", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    const claims = buildClaimsFromEvidence(notebookToEvidence(notebook));

    expect(claims.find((claim) => claim.id === "claim:comparison:accuracy")?.statement)
      .toContain("Model B accuracy");
    expect(claims.find((claim) => claim.id === "claim:comparison:accuracy")?.statement)
      .toContain("Model A accuracy");
  });

  it("derives the title and preserves notebook Markdown prose", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    const evidence = notebookToEvidence(notebook);
    const paper = generatePaper({
      title: "Synthetic Research Study",
      evidence,
      claims: buildClaimsFromEvidence(evidence),
      markdownCells: notebook.cells,
    });
    const contents = paper.blocks.map((block) => block.content).join("\n");

    expect(paper.title).toBe("Synthetic Research Study");
    expect(contents).toContain("Research question");
    expect(contents).toContain("Does Model B outperform Model A");
    expect(paper.blocks.some((block) => block.type === "heading" && block.content === "Statistical interpretation")).toBe(true);
  });

  it("renders valid newlines, inline math, figures, and HTML", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    const evidence = notebookToEvidence(notebook);
    const paper = generatePaper({
      title: "Test",
      evidence,
      claims: buildClaimsFromEvidence(evidence),
    });
    const markdown = renderMarkdown(paper);
    const html = renderHtml(paper);

    expect(markdown).toContain("\n## Results\n");
    expect(markdown).toContain("$$\nF_1");
    expect(markdown).toContain("$P$");
    expect(markdown).toContain("data:image/png;base64,");
    expect(html).toContain("<figure>");
    expect(html).toContain("data:image/png;base64,");
  });

  it("records exact output/source ranges", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    const evidence = notebookToEvidence(notebook);
    const metric = evidence.find((item) => item.kind === "metric");
    const equation = evidence.find((item) => item.kind === "equation" && item.metadata?.display === true);

    expect(metric?.source.outputIndex).toBe(0);
    expect(metric?.source.outputLineStart).toBe(1);
    expect(metric?.source.outputCharStart).toBe(0);
    expect(metric?.source.outputCharEnd).toBeGreaterThan(0);
    expect(equation?.source.sourceLineStart).toBeGreaterThan(0);
    expect(equation?.source.sourceCharStart).toBeGreaterThanOrEqual(0);
    expect(equation?.source.sourceCharEnd).toBeGreaterThan(equation?.source.sourceCharStart ?? -1);
  });

  it("surfaces contradictory metrics and does not claim a winner", () => {
    const first = makeEvidence({
      id: "metric:accuracy:cell-a",
      kind: "metric",
      source: { notebook: "n.ipynb", cellId: "a", cellIndex: 0 },
      label: "Accuracy",
      value: 0.8,
    });
    const second = makeEvidence({
      id: "metric:accuracy:cell-b",
      kind: "metric",
      source: { notebook: "n.ipynb", cellId: "b", cellIndex: 1 },
      label: "Accuracy",
      value: 0.9,
    });
    const conflicts = detectMetricConflicts([first, second]);

    expect(conflicts).toHaveLength(1);
    expect(conflicts[0]?.evidenceIds).toEqual([first.id, second.id]);
  });
});
