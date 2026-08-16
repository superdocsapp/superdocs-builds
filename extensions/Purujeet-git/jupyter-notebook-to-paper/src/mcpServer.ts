import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { promises as fs } from "node:fs";
import { loadNotebook } from "./notebookParser.js";
import { notebookToEvidence } from "./notebookToEvidence.js";
import { buildClaimsFromEvidence } from "./prose.js";
import { generatePaper } from "./paperGenerator.js";
import { renderHtml } from "./html.js";
import { loadState } from "./state.js";
import { commitReviewedRun, runPaperPipeline } from "./orchestrator.js";
import { recordReview } from "./reviewServer.js";
import { detectMetricConflicts } from "./conflicts.js";

export function createPaperMcpServer(): McpServer {
  const server = new McpServer({ name: "jupyter-notebook-to-paper", version: "0.1.0" });

  server.registerTool("paper_parse", {
    description: "Parse an executed Jupyter notebook and return normalized cells.",
    inputSchema: { notebookPath: z.string() },
  }, async ({ notebookPath }) => textResult(await loadNotebook(notebookPath)));

  server.registerTool("paper_run", {
    description: "Run the visible checkpointed notebook-to-paper pipeline.",
    inputSchema: {
      notebookPath: z.string(),
      outputStatePath: z.string(),
      checkpointPath: z.string().optional(),
      resume: z.boolean().optional(),
    },
  }, async ({ notebookPath, outputStatePath, checkpointPath, resume }) => {
    const events: string[] = [];
    const result = await runPaperPipeline({
      notebookPath,
      outputStatePath,
      checkpointPath,
      resume,
      onEvent: (event) => events.push(`${event.stage}:${event.status}:${event.message ?? ""}`),
    });
    return textResult({ runId: result.runId, stages: result.stages, events, outputStatePath });
  });

  server.registerTool("paper_state", {
    description: "Read a generated paper state file and its evidence traceability.",
    inputSchema: { statePath: z.string() },
  }, async ({ statePath }) => textResult(await loadState(statePath)));

  server.registerTool("paper_review_block", {
    description: "Approve or reject one generated paper block.",
    inputSchema: {
      statePath: z.string(),
      blockId: z.string(),
      decision: z.enum(["approve", "reject"]),
    },
  }, async ({ statePath, blockId, decision }) => textResult(await recordReview(statePath, blockId, decision)));

  server.registerTool("paper_export_html", {
    description: "Render a generated paper state as HTML and write it to a file.",
    inputSchema: { statePath: z.string(), outputPath: z.string() },
  }, async ({ statePath, outputPath }) => {
    const state = await loadState(statePath);
    const html = renderHtml(state.paper);
    await fs.writeFile(outputPath, html, "utf8");
    return textResult({ outputPath, bytes: Buffer.byteLength(html, "utf8") });
  });

  server.registerTool("paper_commit_review", {
    description: "Commit a reviewed paper after every block has an approve/reject decision.",
    inputSchema: { checkpointPath: z.string() },
  }, async ({ checkpointPath }) => {
    const result = await commitReviewedRun(checkpointPath);
    return textResult({ runId: result.runId, outputStatePath: result.outputStatePath, status: "committed" });
  });

  server.registerTool("paper_preview", {
    description: "Generate a paper preview in memory from a notebook without committing state.",
    inputSchema: { notebookPath: z.string() },
  }, async ({ notebookPath }) => {
    const notebook = await loadNotebook(notebookPath);
    const evidence = notebookToEvidence(notebook);
    const conflicts = detectMetricConflicts(evidence);
    const paper = generatePaper({
      title: notebook.cells.find((cell) => cell.cellType === "markdown")?.source.split(/\r?\n/)[0]?.replace(/^#\s+/, "") || "Notebook Research Paper",
      evidence,
      claims: buildClaimsFromEvidence(evidence, conflicts),
      markdownCells: notebook.cells,
      conflicts,
    });
    return textResult({ paper, html: renderHtml(paper) });
  });

  return server;
}

export async function startPaperMcpServer(): Promise<void> {
  const server = createPaperMcpServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

function textResult(value: unknown): { content: Array<{ type: "text"; text: string }> } {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}
