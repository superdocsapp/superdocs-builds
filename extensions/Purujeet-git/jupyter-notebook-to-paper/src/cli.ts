import { promises as fs } from "node:fs";
import path from "node:path";
import { loadNotebook } from "./notebookParser.js";
import { notebookToEvidence } from "./notebookToEvidence.js";
import { buildClaimsFromEvidence } from "./prose.js";
import { generatePaper } from "./paperGenerator.js";
import { renderMarkdown } from "./markdown.js";
import { renderHtml } from "./html.js";
import { createSnapshot, diffEvidence, mergeIncrementalPaper } from "./incremental.js";
import { loadState, saveState } from "./state.js";
import { SuperDocsClient } from "./superdocs.js";
import { commitReviewedRun, runPaperPipeline } from "./orchestrator.js";
import { startReviewServer } from "./reviewServer.js";
import { startPaperMcpServer } from "./mcpServer.js";
import { detectMetricConflicts } from "./conflicts.js";
import { readUsageLedger, summarizeUsage } from "./telemetry.js";

async function main(): Promise<void> {
  const [command, firstArg, secondArg, thirdArg, fourthArg, fifthArg] = process.argv.slice(2);

  switch (command) {
    case "parse":
      await parseCommand(firstArg);
      break;
    case "generate":
      await generateCommand(firstArg);
      break;
    case "snapshot":
      await snapshotCommand(firstArg, secondArg);
      break;
    case "diff":
      await diffCommand(firstArg, secondArg);
      break;
    case "update":
      await updateCommand(firstArg, secondArg, thirdArg);
      break;
    case "run":
      await runCommand(firstArg, secondArg, thirdArg, fourthArg, fifthArg);
      break;
    case "review":
      await reviewCommand(firstArg, secondArg);
      break;
    case "review-commit":
      await reviewCommitCommand(firstArg);
      break;
    case "mcp":
      await startPaperMcpServer();
      break;
    case "telemetry":
      await telemetryCommand(firstArg);
      break;
    case "superdocs-chat":
      await superDocsChatCommand(firstArg, secondArg, thirdArg);
      break;
    case "superdocs-async-chat":
      await superDocsAsyncChatCommand(firstArg, secondArg, thirdArg);
      break;
    case "superdocs-job":
      await superDocsJobCommand(firstArg, secondArg);
      break;
    case "superdocs-approve":
      await superDocsApproveCommand(firstArg, secondArg, thirdArg, fourthArg);
      break;
    case "superdocs-export":
      await superDocsExportCommand(firstArg, secondArg, thirdArg);
      break;
    default:
      printUsage();
      process.exitCode = 1;
  }
}

async function parseCommand(notebookPath: string | undefined): Promise<void> {
  if (!notebookPath) throw new Error("Usage: npm run dev -- parse <notebook.ipynb>");
  const notebook = await loadNotebook(notebookPath);
  console.log(JSON.stringify(notebook, null, 2));
}

async function generateCommand(notebookPath: string | undefined): Promise<void> {
  if (!notebookPath) throw new Error("Usage: npm run dev -- generate <notebook.ipynb>");

  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const claims = buildClaimsFromEvidence(evidence, conflicts);
  const paper = generatePaper({
    title: notebookTitle(notebook),
    evidence,
    claims,
    markdownCells: notebook.cells,
    conflicts,
  });

  const markdownPath = path.resolve(
    path.dirname(notebook.path),
    "generated-paper.md",
  );
  await fs.writeFile(markdownPath, renderMarkdown(paper), "utf8");

  const snapshotPath = path.resolve(
    path.dirname(notebook.path),
    "state-v1.json",
  );
  await saveState(
    snapshotPath,
    {
      snapshot: createSnapshot("v1", notebook.path, evidence),
      paper,
    },
  );

  console.log(`Paper preview: ${markdownPath}`);
  console.log(`State snapshot: ${snapshotPath}`);
}

async function snapshotCommand(
  notebookPath: string | undefined,
  outputPath: string | undefined,
): Promise<void> {
  if (!notebookPath || !outputPath) {
    throw new Error("Usage: npm run dev -- snapshot <notebook.ipynb> <state.json>");
  }

  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const claims = buildClaimsFromEvidence(evidence, conflicts);
  const paper = generatePaper({
    title: notebookTitle(notebook),
    evidence,
    claims,
    markdownCells: notebook.cells,
    conflicts,
  });

  await saveState(outputPath, {
    snapshot: createSnapshot("snapshot", notebook.path, evidence),
    paper,
  });

  console.log(`Saved state: ${path.resolve(outputPath)}`);
}

async function diffCommand(
  beforePath: string | undefined,
  afterPath: string | undefined,
): Promise<void> {
  if (!beforePath || !afterPath) {
    throw new Error("Usage: npm run dev -- diff <before.json> <after.json>");
  }

  const before = await loadState(beforePath);
  const after = await loadState(afterPath);

  const diff = diffEvidence(before.snapshot, after.snapshot, after.paper);
  console.log(JSON.stringify(diff, null, 2));
}

async function updateCommand(
  notebookPath: string | undefined,
  previousStatePath: string | undefined,
  outputStatePath: string | undefined,
): Promise<void> {
  if (!notebookPath || !previousStatePath || !outputStatePath) {
    throw new Error("Usage: npm run dev -- update <notebook.ipynb> <previous-state.json> <output-state.json>");
  }

  const previous = await loadState(previousStatePath);
  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const claims = buildClaimsFromEvidence(evidence, conflicts);
  const regenerated = generatePaper({ title: notebookTitle(notebook), evidence, claims, markdownCells: notebook.cells, conflicts });
  const diff = diffEvidence(
    previous.snapshot,
    createSnapshot("updated", notebook.path, evidence),
    regenerated,
  );
  const paper = mergeIncrementalPaper(previous.paper, regenerated, diff.affectedBlockIds);

  await saveState(outputStatePath, {
    snapshot: createSnapshot("updated", notebook.path, evidence),
    paper,
  });
  const markdownPath = path.resolve(path.dirname(outputStatePath), "generated-paper.md");
  await fs.writeFile(markdownPath, renderMarkdown(paper), "utf8");
  console.log(JSON.stringify({
    updatedState: path.resolve(outputStatePath),
    markdownPath,
    changes: diff.changes,
    affectedBlockIds: diff.affectedBlockIds,
  }, null, 2));
}

async function runCommand(
  notebookPath: string | undefined,
  outputStatePath: string | undefined,
  checkpointPath: string | undefined,
  resume: string | undefined,
  decisions: string | undefined,
): Promise<void> {
  if (!notebookPath || !outputStatePath) {
    throw new Error("Usage: npm run dev -- run <notebook.ipynb> <state.json> [checkpoint.json] [resume]");
  }
  const result = await runPaperPipeline({
    notebookPath,
    outputStatePath,
    checkpointPath,
    resume: resume === "resume",
    autoApproveReview: resume === "auto",
    onDecision: (stage, error, attempt) => {
      const configured = new Map((decisions ?? "").split(",").filter(Boolean).map((entry) => {
        const [name, decision] = entry.split(":");
        return [name, decision] as const;
      }));
      const selected = configured.get(stage);
      if (selected === "retry" || selected === "skip" || selected === "escalate") {
        console.log(`[${stage}] decision=${selected} attempt=${attempt}: ${error.message}`);
        return selected;
      }
      return attempt <= 1 ? "retry" : "escalate";
    },
    onEvent: (event) => console.log(`[${event.stage}] ${event.status}: ${event.message ?? ""}`),
  });
  console.log(JSON.stringify({ runId: result.runId, stages: result.stages, outputStatePath }, null, 2));
}

async function reviewCommand(
  statePath: string | undefined,
  port: string | undefined,
): Promise<void> {
  if (!statePath) throw new Error("Usage: npm run dev -- review <state.json> [port]");
  const selectedPort = port ? Number(port) : 4173;
  await startReviewServer({ statePath, port: selectedPort });
  console.log(`Review UI: http://127.0.0.1:${selectedPort}/`);
}

async function reviewCommitCommand(checkpointPath: string | undefined): Promise<void> {
  if (!checkpointPath) throw new Error("Usage: npm run dev -- review-commit <checkpoint.json>");
  const result = await commitReviewedRun(checkpointPath);
  console.log(JSON.stringify({ runId: result.runId, status: "committed", outputStatePath: result.outputStatePath }, null, 2));
}

async function telemetryCommand(usagePath: string | undefined): Promise<void> {
  const selectedPath = usagePath ?? process.env.SUPERDOCS_USAGE_PATH ?? "superdocs-usage.json";
  const ledger = await readUsageLedger(selectedPath);
  console.log(JSON.stringify({ path: selectedPath, summary: summarizeUsage(ledger), records: ledger.records }, null, 2));
}

async function superDocsChatCommand(
  notebookPath: string | undefined,
  instruction: string | undefined,
  sessionId: string | undefined,
): Promise<void> {
  if (!notebookPath || !instruction) {
    throw new Error("Usage: npm run dev -- superdocs-chat <notebook.ipynb> <instruction> [session-id]");
  }
  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const paper = generatePaper({
    title: notebookTitle(notebook),
    evidence,
    claims: buildClaimsFromEvidence(evidence, conflicts),
    markdownCells: notebook.cells,
    conflicts,
  });
  const response = await SuperDocsClient.fromEnv().chat({
    message: instruction,
    session_id: sessionId ?? `notebook-${Date.now()}`,
    document_html: renderHtml(paper),
    approval_mode: "ask_every_time",
  });
  console.log(JSON.stringify(response, null, 2));
}

async function superDocsApproveCommand(
  sessionId: string | undefined,
  jobId: string | undefined,
  approved: string | undefined,
  changeIds: string | undefined,
): Promise<void> {
  if (!sessionId || !jobId || !approved) {
    throw new Error("Usage: npm run dev -- superdocs-approve <session-id> <job-id> <true|false> [change-id,...]");
  }
  const changes = changeIds
    ? changeIds.split(",").filter(Boolean).map((changeId) => ({ changeId, approved: approved.toLowerCase() === "true" }))
    : undefined;
  const result = await SuperDocsClient.fromEnv().approve(sessionId, {
    jobId,
    approved: approved.toLowerCase() === "true",
    changes,
  });
  console.log(JSON.stringify(result, null, 2));
}

async function superDocsAsyncChatCommand(
  notebookPath: string | undefined,
  instruction: string | undefined,
  sessionId: string | undefined,
): Promise<void> {
  if (!notebookPath || !instruction) {
    throw new Error("Usage: npm run dev -- superdocs-async-chat <notebook.ipynb> <instruction> [session-id]");
  }
  const notebook = await loadNotebook(notebookPath);
  const evidence = notebookToEvidence(notebook);
  const conflicts = detectMetricConflicts(evidence);
  const paper = generatePaper({
    title: notebookTitle(notebook),
    evidence,
    claims: buildClaimsFromEvidence(evidence, conflicts),
    markdownCells: notebook.cells,
    conflicts,
  });
  const response = await SuperDocsClient.fromEnv().chatAsync({
    message: instruction,
    session_id: sessionId ?? `notebook-${Date.now()}`,
    document_html: renderHtml(paper),
    approval_mode: "ask_every_time",
  });
  console.log(JSON.stringify(response, null, 2));
}

function notebookTitle(notebook: Awaited<ReturnType<typeof loadNotebook>>): string {
  const titleLine = notebook.cells
    .filter((cell) => cell.cellType === "markdown")
    .flatMap((cell) => cell.source.split(/\r?\n/))
    .find((line) => /^#\s+[^#]/.test(line.trim()));
  return titleLine?.replace(/^#\s+/, "").trim() || "Notebook Research Paper";
}

async function superDocsJobCommand(
  jobId: string | undefined,
  maxWaitMs: string | undefined,
): Promise<void> {
  if (!jobId) {
    throw new Error("Usage: npm run dev -- superdocs-job <job-id> [max-wait-ms]");
  }
  const client = SuperDocsClient.fromEnv();
  const result = maxWaitMs
    ? await client.waitForJob(jobId, { maxWaitMs: Number(maxWaitMs) })
    : await client.getJob(jobId);
  console.log(JSON.stringify(result, null, 2));
}

async function superDocsExportCommand(
  htmlPath: string | undefined,
  outputPath: string | undefined,
  format: string | undefined,
): Promise<void> {
  if (!htmlPath || !outputPath || (format !== "doc" && format !== "docx")) {
    throw new Error("Usage: npm run dev -- superdocs-export <document.html> <output.docx> <doc|docx>");
  }
  const html = await fs.readFile(htmlPath, "utf8");
  const exported = await SuperDocsClient.fromEnv().exportDocument({ html, format });
  await fs.writeFile(outputPath, exported);
  console.log(`Exported document: ${path.resolve(outputPath)}`);
}

function printUsage(): void {
  console.log(
    [
      "Jupyter Notebook to Paper",
      "",
      "Commands:",
      "  parse <notebook.ipynb>",
      "  generate <notebook.ipynb>",
      "  snapshot <notebook.ipynb> <state.json>",
      "  diff <before.json> <after.json>",
      "  update <notebook.ipynb> <previous-state.json> <output-state.json>",
      "  run <notebook.ipynb> <state.json> [checkpoint.json] [resume|auto] [stage:retry|skip|escalate,...]",
      "  review <state.json> [port]",
      "  review-commit <checkpoint.json>",
      "  mcp",
      "  telemetry [usage.json]",
      "  superdocs-chat <notebook.ipynb> <instruction> [session-id]",
      "  superdocs-async-chat <notebook.ipynb> <instruction> [session-id]",
      "  superdocs-job <job-id> [max-wait-ms]",
      "  superdocs-approve <session-id> <job-id> <true|false> [change-id,...]",
      "  superdocs-export <document.html> <output.docx> <doc|docx>",
    ].join("\n"),
  );
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
