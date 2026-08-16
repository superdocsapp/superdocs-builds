import { describe, expect, it } from "vitest";
import { loadNotebook } from "../src/notebookParser.js";

describe("NotebookParser", () => {
  it("parses the synthetic notebook", async () => {
    const notebook = await loadNotebook("examples/synthetic_research.ipynb");
    expect(notebook.cells.length).toBeGreaterThan(0);
    expect(notebook.cells.some((cell) => cell.id === "metrics")).toBe(true);
    expect(notebook.cells.some((cell) => cell.id === "figure-model-comparison")).toBe(true);
  });
});
