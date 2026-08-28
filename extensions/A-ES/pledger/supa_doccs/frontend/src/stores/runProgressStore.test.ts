import { describe, it, expect, beforeEach } from "vitest";
import { useRunProgressStore } from "./runProgressStore";
import type { PipelineProgress, RunSummary } from "@/types/review";

describe("runProgressStore", () => {
  beforeEach(() => {
    useRunProgressStore.getState().reset();
  });

  describe("initial state", () => {
    it("has correct default values", () => {
      const state = useRunProgressStore.getState();
      expect(state.currentNode).toBeNull();
      expect(state.completedNodes).toEqual([]);
      expect(state.nodeStatus).toBeNull();
      expect(state.runStatus).toBe("running");
      expect(state.runs).toEqual([]);
      expect(state.selectedRunId).toBeNull();
    });
  });

  describe("setProgress", () => {
    it("updates currentNode, completedNodes, nodeStatus, and runStatus from PipelineProgress", () => {
      const progress: PipelineProgress = {
        current_node: "extract_claims",
        completed_nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"],
        node_status: "completed",
        run_status: "running",
      };

      useRunProgressStore.getState().setProgress(progress);
      const state = useRunProgressStore.getState();

      expect(state.currentNode).toBe("extract_claims");
      expect(state.completedNodes).toEqual([
        "ingest",
        "extract_text",
        "classify_document",
        "chunk",
        "embed",
      ]);
      expect(state.nodeStatus).toBe("completed");
      expect(state.runStatus).toBe("running");
    });

    it("handles completed run with null current_node", () => {
      const progress: PipelineProgress = {
        current_node: null,
        completed_nodes: ["ingest", "extract_text", "finalize"],
        node_status: null,
        run_status: "completed",
      };

      useRunProgressStore.getState().setProgress(progress);
      const state = useRunProgressStore.getState();

      expect(state.currentNode).toBeNull();
      expect(state.runStatus).toBe("completed");
      expect(state.nodeStatus).toBeNull();
    });

    it("handles error node_status", () => {
      const progress: PipelineProgress = {
        current_node: "match_rules",
        completed_nodes: ["ingest"],
        node_status: "error",
        run_status: "failed",
      };

      useRunProgressStore.getState().setProgress(progress);
      const state = useRunProgressStore.getState();

      expect(state.nodeStatus).toBe("error");
      expect(state.runStatus).toBe("failed");
    });
  });

  describe("setRuns", () => {
    it("replaces the runs array", () => {
      const runs: RunSummary[] = [
        { id: "run-1", status: "completed", started_at: "2024-01-01T00:00:00Z", ended_at: "2024-01-01T01:00:00Z" },
        { id: "run-2", status: "running", started_at: "2024-01-02T00:00:00Z", ended_at: null },
      ];

      useRunProgressStore.getState().setRuns(runs);
      expect(useRunProgressStore.getState().runs).toEqual(runs);
    });

    it("replaces existing runs with new array", () => {
      const initialRuns: RunSummary[] = [
        { id: "run-1", status: "completed", started_at: "2024-01-01T00:00:00Z", ended_at: "2024-01-01T01:00:00Z" },
      ];
      const newRuns: RunSummary[] = [
        { id: "run-3", status: "paused", started_at: "2024-01-03T00:00:00Z", ended_at: null },
      ];

      useRunProgressStore.getState().setRuns(initialRuns);
      useRunProgressStore.getState().setRuns(newRuns);
      expect(useRunProgressStore.getState().runs).toEqual(newRuns);
    });
  });

  describe("setSelectedRunId", () => {
    it("sets the selected run ID", () => {
      useRunProgressStore.getState().setSelectedRunId("run-42");
      expect(useRunProgressStore.getState().selectedRunId).toBe("run-42");
    });

    it("clears the selected run ID with null", () => {
      useRunProgressStore.getState().setSelectedRunId("run-42");
      useRunProgressStore.getState().setSelectedRunId(null);
      expect(useRunProgressStore.getState().selectedRunId).toBeNull();
    });
  });

  describe("reset", () => {
    it("clears all state back to defaults", () => {
      // Set some state first
      useRunProgressStore.getState().setProgress({
        current_node: "extract_claims",
        completed_nodes: ["ingest", "extract_text"],
        node_status: "completed",
        run_status: "running",
      });
      useRunProgressStore.getState().setRuns([
        { id: "run-1", status: "running", started_at: "2024-01-01T00:00:00Z", ended_at: null },
      ]);
      useRunProgressStore.getState().setSelectedRunId("run-1");

      // Reset
      useRunProgressStore.getState().reset();

      const state = useRunProgressStore.getState();
      expect(state.currentNode).toBeNull();
      expect(state.completedNodes).toEqual([]);
      expect(state.nodeStatus).toBeNull();
      expect(state.runStatus).toBe("running");
      expect(state.runs).toEqual([]);
      expect(state.selectedRunId).toBeNull();
    });
  });
});
