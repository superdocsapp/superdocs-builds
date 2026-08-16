import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { loadNotebook } from "./notebookParser.js";
import { notebookToEvidence } from "./notebookToEvidence.js";
import { buildClaimsFromEvidence } from "./prose.js";
import { generatePaper } from "./paperGenerator.js";
import { createSnapshot } from "./incremental.js";
import { acquireExclusiveLock, closeExclusiveLock, releaseExclusiveLock, saveState } from "./state.js";
import { detectMetricConflicts } from "./conflicts.js";
import type { Claim, Evidence, NotebookDocument, PaperDocument } from "./types.js";

export type RunStage = "parse" | "evidence" | "claims" | "paper" | "review" | "commit";
export type StageStatus = "pending" | "running" | "completed" | "awaiting_review" | "skipped" | "failed" | "escalated";
export type StageDecision = "retry" | "skip" | "escalate";

export interface StageRecord {
  stage: RunStage;
  status: StageStatus;
  attempts: number;
  startedAt?: string;
  completedAt?: string;
  error?: string;
}

export interface RunCheckpoint {
  runId: string;
  notebookPath: string;
  outputStatePath: string;
  createdAt: string;
  updatedAt: string;
  stages: StageRecord[];
  notebook?: NotebookDocument;
  evidence?: Evidence[];
  claims?: Claim[];
  paper?: PaperDocument;
  conflicts?: import("./types.js").MetricConflict[];
}

export interface OrchestratorOptions {
  notebookPath: string;
  outputStatePath: string;
  checkpointPath?: string;
  resume?: boolean;
  maxRetries?: number;
  onEvent?: (event: { runId: string; stage: RunStage; status: StageStatus; message?: string }) => void;
  onDecision?: (stage: RunStage, error: Error, attempt: number) => StageDecision;
  autoApproveReview?: boolean;
}

const STAGES: RunStage[] = ["parse", "evidence", "claims", "paper", "review", "commit"];

export async function runPaperPipeline(options: OrchestratorOptions): Promise<RunCheckpoint> {
  const checkpointPath = options.checkpointPath ?? `${options.outputStatePath}.run.json`;
  const checkpoint = options.resume ? await loadCheckpoint(checkpointPath) : undefined;
  const pipelineLockPath = `${options.outputStatePath}.pipeline.lock`;
  const pipelineLock = await acquireExclusiveLock(pipelineLockPath, options.outputStatePath);
  const run = checkpoint && checkpoint.notebookPath === path.resolve(options.notebookPath)
    ? checkpoint
    : createCheckpoint(options);
  const maxRetries = options.maxRetries ?? 1;

  await executeStage(run, "parse", maxRetries, options, async () => {
    run.notebook ??= await loadNotebook(options.notebookPath);
  });
  await executeStage(run, "evidence", maxRetries, options, async () => {
    if (!run.notebook) throw new Error("Parser stage did not produce a notebook.");
    run.evidence ??= notebookToEvidence(run.notebook);
  });
  if (run.evidence && !run.conflicts) run.conflicts = detectMetricConflicts(run.evidence);
  await executeStage(run, "claims", maxRetries, options, async () => {
    if (!run.evidence) throw new Error("Evidence stage did not produce evidence.");
    run.conflicts ??= detectMetricConflicts(run.evidence);
    run.claims ??= buildClaimsFromEvidence(run.evidence, run.conflicts);
  });
  await executeStage(run, "paper", maxRetries, options, async () => {
    if (!run.evidence || !run.claims) throw new Error("Claims stage did not produce claims.");
    run.paper ??= generatePaper({
      title: deriveTitle(run.notebook),
      evidence: run.evidence,
      claims: run.claims,
      markdownCells: run.notebook?.cells,
      conflicts: run.conflicts,
    });
  });
  if (!options.autoApproveReview) {
    if (!run.paper || !run.notebook || !run.evidence) throw new Error("Run is missing review artifacts.");
    const draftPath = `${options.outputStatePath}.draft.json`;
    await saveState(draftPath, {
      snapshot: createSnapshot(run.runId, run.notebook.path, run.evidence),
      paper: run.paper,
    });
    const reviewRecord = run.stages.find((item) => item.stage === "review");
    if (reviewRecord?.status !== "completed") {
      if (reviewRecord) {
        reviewRecord.status = "awaiting_review";
        reviewRecord.startedAt ??= new Date().toISOString();
      }
      run.updatedAt = new Date().toISOString();
      await saveCheckpoint(checkpointPath, run);
      emit(options, run, "review", "awaiting_review", `Review draft ready at ${draftPath}.`);
      await closeExclusiveLock(pipelineLock, pipelineLockPath);
    }
    return run;
  }

  await executeStage(run, "review", maxRetries, options, async () => {
    if (!run.paper) throw new Error("Paper stage did not produce a paper.");
  });
  await executeStage(run, "commit", maxRetries, options, async () => {
    if (!run.notebook || !run.evidence || !run.paper) throw new Error("Run is missing commit artifacts.");
    await saveState(options.outputStatePath, {
      snapshot: createSnapshot(run.runId, run.notebook.path, run.evidence),
      paper: run.paper,
    });
  });

  await saveCheckpoint(checkpointPath, run);
  await releaseExclusiveLock(pipelineLock, pipelineLockPath);
  return run;
}

export async function commitReviewedRun(checkpointPath: string): Promise<RunCheckpoint> {
  const run = JSON.parse(await fs.readFile(checkpointPath, "utf8")) as RunCheckpoint;
  if (!run.paper) throw new Error("Checkpoint does not contain a paper to commit.");
  const draftPath = `${run.outputStatePath}.draft.json`;
  const pipelineLockPath = `${run.outputStatePath}.pipeline.lock`;
  const pipelineLock = await acquireExclusiveLock(pipelineLockPath, run.outputStatePath);
  const reviewsPath = `${draftPath}.reviews.json`;
  const reviews = await loadReviews(reviewsPath);
  const decisions = new Map(reviews.map((review) => [review.blockId, review.decision]));
  const missing = run.paper.blocks.filter((block) => !decisions.has(block.id)).map((block) => block.id);
  if (missing.length > 0) throw new Error(`Review is incomplete; undecided blocks: ${missing.join(", ")}`);
  const rejected = new Set(reviews.filter((review) => review.decision === "reject").map((review) => review.blockId));
  const committedPaper = { ...run.paper, blocks: run.paper.blocks.filter((block) => !rejected.has(block.id)) };
  const notebook = run.notebook ?? await loadNotebookFromCheckpoint(run);
  const evidence = run.evidence ?? [];
  await saveState(run.outputStatePath, {
    snapshot: createSnapshot(run.runId, notebook.path, evidence),
    paper: committedPaper,
  });
  const reviewStage = run.stages.find((item) => item.stage === "review");
  const commitStage = run.stages.find((item) => item.stage === "commit");
  if (reviewStage) { reviewStage.status = "completed"; reviewStage.completedAt = new Date().toISOString(); }
  if (commitStage) { commitStage.status = "completed"; commitStage.attempts = Math.max(commitStage.attempts, 1); commitStage.completedAt = new Date().toISOString(); }
  run.paper = committedPaper;
  run.updatedAt = new Date().toISOString();
  await saveCheckpoint(checkpointPath, run);
  await releaseExclusiveLock(pipelineLock, pipelineLockPath);
  return run;
}

function createCheckpoint(options: OrchestratorOptions): RunCheckpoint {
  const now = new Date().toISOString();
  return {
    runId: randomUUID(),
    notebookPath: path.resolve(options.notebookPath),
    outputStatePath: path.resolve(options.outputStatePath),
    createdAt: now,
    updatedAt: now,
    stages: STAGES.map((stage) => ({ stage, status: "pending", attempts: 0 })),
  };
}

async function executeStage(
  run: RunCheckpoint,
  stage: RunStage,
  maxRetries: number,
  options: OrchestratorOptions,
  action: () => Promise<void>,
): Promise<void> {
  const record = run.stages.find((item) => item.stage === stage);
  if (!record) throw new Error(`Unknown stage: ${stage}`);
  if (record.status === "completed" || record.status === "skipped") return;

  while (true) {
    record.status = "running";
    record.attempts += 1;
    record.startedAt = new Date().toISOString();
    emit(options, run, stage, "running", `Stage started (attempt ${record.attempts}).`);
    try {
      await action();
      record.status = "completed";
      record.completedAt = new Date().toISOString();
      run.updatedAt = new Date().toISOString();
      await saveCheckpoint(options.checkpointPath ?? `${options.outputStatePath}.run.json`, run);
      emit(options, run, stage, "completed", "Stage completed.");
      return;
    } catch (unknownError) {
      const error = unknownError instanceof Error ? unknownError : new Error(String(unknownError));
      record.error = error.message;
      const decision = options.onDecision?.(stage, error, record.attempts)
        ?? (record.attempts <= maxRetries ? "retry" : "escalate");
      if (decision === "retry" && record.attempts <= maxRetries) continue;
      record.status = decision === "skip" ? "skipped" : "escalated";
      run.updatedAt = new Date().toISOString();
      emit(options, run, stage, record.status, error.message);
      if (decision === "skip") return;
      await saveCheckpoint(options.checkpointPath ?? `${options.outputStatePath}.run.json`, run);
      throw error;
    }
  }
}

function emit(
  options: OrchestratorOptions,
  run: RunCheckpoint,
  stage: RunStage,
  status: StageStatus,
  message: string,
): void {
  options.onEvent?.({ runId: run.runId, stage, status, message });
}

function deriveTitle(notebook: NotebookDocument | undefined): string {
  const heading = notebook?.cells
    .filter((cell) => cell.cellType === "markdown")
    .flatMap((cell) => cell.source.split(/\r?\n/))
    .find((line) => /^#\s+[^#]/.test(line.trim()));
  return heading?.replace(/^#\s+/, "").trim() || "Notebook Research Paper";
}

async function loadCheckpoint(checkpointPath: string): Promise<RunCheckpoint | undefined> {
  try {
    return JSON.parse(await fs.readFile(checkpointPath, "utf8")) as RunCheckpoint;
  } catch {
    return undefined;
  }
}

async function saveCheckpoint(checkpointPath: string, checkpoint: RunCheckpoint): Promise<void> {
  const temporaryPath = `${checkpointPath}.tmp-${process.pid}-${Date.now()}`;
  await fs.writeFile(temporaryPath, JSON.stringify(checkpoint, null, 2), "utf8");
  await fs.rename(temporaryPath, checkpointPath);
}

async function loadReviews(reviewsPath: string): Promise<Array<{ blockId: string; decision: "approve" | "reject" }>> {
  try {
    return JSON.parse(await fs.readFile(reviewsPath, "utf8")) as Array<{ blockId: string; decision: "approve" | "reject" }>;
  } catch {
    return [];
  }
}

async function loadNotebookFromCheckpoint(run: RunCheckpoint): Promise<NotebookDocument> {
  if (run.notebook) return run.notebook;
  return loadNotebook(run.notebookPath);
}
