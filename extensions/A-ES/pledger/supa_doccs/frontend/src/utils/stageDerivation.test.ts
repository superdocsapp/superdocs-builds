import { describe, it, expect } from "vitest";
import { deriveStageStatus } from "./stageDerivation";
import type { StageDefinition } from "@/utils/constants";

const understandStage: StageDefinition = {
  name: "Understand",
  nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"],
};

const examineStage: StageDefinition = {
  name: "Examine",
  nodes: [
    "extract_claims",
    "match_rules",
    "match_rules_against_sources",
    "merge_findings",
    "score_confidence",
  ],
};

const stayAliveStage: StageDefinition = {
  name: "Stay-Alive",
  nodes: ["route_to_queue", "human_review", "finalize"],
};

describe("deriveStageStatus", () => {
  it('returns "complete" when all nodes in the stage are completed', () => {
    const completedNodes = [
      "ingest",
      "extract_text",
      "classify_document",
      "chunk",
      "embed",
    ];
    expect(deriveStageStatus(understandStage, completedNodes, null)).toBe(
      "complete"
    );
  });

  it('returns "complete" even when currentNode is in a later stage', () => {
    const completedNodes = [
      "ingest",
      "extract_text",
      "classify_document",
      "chunk",
      "embed",
    ];
    expect(
      deriveStageStatus(understandStage, completedNodes, "extract_claims")
    ).toBe("complete");
  });

  it('returns "in-progress" when currentNode is one of the stage nodes', () => {
    const completedNodes = ["ingest", "extract_text"];
    expect(
      deriveStageStatus(understandStage, completedNodes, "classify_document")
    ).toBe("in-progress");
  });

  it('returns "in-progress" when currentNode is the first node in the stage with no completions', () => {
    expect(deriveStageStatus(understandStage, [], "ingest")).toBe(
      "in-progress"
    );
  });

  it('returns "pending" when no nodes are completed and currentNode is null', () => {
    expect(deriveStageStatus(examineStage, [], null)).toBe("pending");
  });

  it('returns "pending" when no nodes are completed and currentNode is in a different stage', () => {
    expect(deriveStageStatus(examineStage, [], "ingest")).toBe("pending");
  });

  it('returns "pending" when some nodes in previous stage are done but this stage has not started', () => {
    const completedNodes = ["ingest", "extract_text"];
    expect(
      deriveStageStatus(stayAliveStage, completedNodes, "classify_document")
    ).toBe("pending");
  });

  it("handles a stage with a single node that is complete", () => {
    const singleNodeStage: StageDefinition = {
      name: "Single",
      nodes: ["only_node"],
    };
    expect(deriveStageStatus(singleNodeStage, ["only_node"], null)).toBe(
      "complete"
    );
  });

  it("handles a stage with a single node that is in-progress", () => {
    const singleNodeStage: StageDefinition = {
      name: "Single",
      nodes: ["only_node"],
    };
    expect(deriveStageStatus(singleNodeStage, [], "only_node")).toBe(
      "in-progress"
    );
  });

  it('prioritizes "complete" over "in-progress" when all nodes are done and currentNode is in the stage', () => {
    const completedNodes = [
      "route_to_queue",
      "human_review",
      "finalize",
    ];
    // Even if currentNode happens to be in the same stage, completeness wins
    expect(
      deriveStageStatus(stayAliveStage, completedNodes, "finalize")
    ).toBe("complete");
  });
});
