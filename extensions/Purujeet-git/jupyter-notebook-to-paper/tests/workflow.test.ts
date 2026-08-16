import { describe, expect, it } from "vitest";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { commitReviewedRun, runPaperPipeline } from "../src/orchestrator.js";
import { recordReview, startReviewServer } from "../src/reviewServer.js";
import { loadState } from "../src/state.js";

describe("orchestrated review workflow", () => {
  it("checkpoints visible stages and resumes without redoing completed work", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-paper-"));
    const outputStatePath = path.join(directory, "state.json");
    const checkpointPath = path.join(directory, "run.json");
    const events: string[] = [];

    const first = await runPaperPipeline({
      notebookPath: "examples/synthetic_research.ipynb",
      outputStatePath,
      checkpointPath,
      autoApproveReview: true,
      onEvent: (event) => events.push(`${event.stage}:${event.status}`),
    });
    const second = await runPaperPipeline({
      notebookPath: "examples/synthetic_research.ipynb",
      outputStatePath,
      checkpointPath,
      resume: true,
      autoApproveReview: true,
    });

    expect(first.runId).toBe(second.runId);
    expect(first.stages.every((stage) => stage.status === "completed")).toBe(true);
    expect(events).toContain("parse:completed");
    expect(JSON.parse(await fs.readFile(checkpointPath, "utf8")).stages).toHaveLength(6);
    expect((await loadState(outputStatePath)).paper.blocks.length).toBeGreaterThan(0);
  });

  it("serves paper blocks and records item-level review decisions", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-review-"));
    const outputStatePath = path.join(directory, "state.json");
    await runPaperPipeline({ notebookPath: "examples/synthetic_research.ipynb", outputStatePath, autoApproveReview: true });
    const state = await loadState(outputStatePath);
    const blockId = state.paper.blocks[0]?.id;
    if (!blockId) throw new Error("Expected generated paper block.");

    const server = await startReviewServer({ statePath: outputStatePath, port: 0 });
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Review server did not expose a port.");
    const baseUrl = `http://127.0.0.1:${address.port}`;
    const page = await fetch(`${baseUrl}/`);
    const review = await fetch(`${baseUrl}/api/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ blockId, decision: "approve" }),
    });
    const stateResponse = await fetch(`${baseUrl}/api/state`);
    const stateJson = await stateResponse.json() as { reviews: Array<{ blockId: string; decision: string }> };
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));

    expect(page.status).toBe(200);
    expect(review.status).toBe(200);
    expect(stateJson.reviews).toContainEqual(expect.objectContaining({ blockId, decision: "approve" }));
  });

  it("does not commit until every block has a review decision", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-gate-"));
    const outputStatePath = path.join(directory, "state.json");
    const checkpointPath = path.join(directory, "run.json");
    const run = await runPaperPipeline({ notebookPath: "examples/synthetic_research.ipynb", outputStatePath, checkpointPath });

    expect(run.stages.find((stage) => stage.stage === "review")?.status).toBe("awaiting_review");
    await expect(loadState(outputStatePath)).rejects.toThrow();
  });

  it("commits only approved blocks after the human gate", async () => {
    const directory = await fs.mkdtemp(path.join(os.tmpdir(), "notebook-commit-"));
    const outputStatePath = path.join(directory, "state.json");
    const checkpointPath = path.join(directory, "run.json");
    await runPaperPipeline({ notebookPath: "examples/synthetic_research.ipynb", outputStatePath, checkpointPath });
    const draft = await loadState(`${outputStatePath}.draft.json`);
    const firstBlock = draft.paper.blocks[0];
    if (!firstBlock) throw new Error("Expected a draft block.");
    for (const block of draft.paper.blocks) {
      await recordReview(`${outputStatePath}.draft.json`, block.id, block.id === firstBlock.id ? "reject" : "approve");
    }

    const committed = await commitReviewedRun(checkpointPath);
    const finalState = await loadState(outputStatePath);
    expect(committed.stages.find((stage) => stage.stage === "commit")?.status).toBe("completed");
    expect(finalState.paper.blocks.some((block) => block.id === firstBlock.id)).toBe(false);
    expect(finalState.paper.blocks.length).toBe(draft.paper.blocks.length - 1);
  });
});
