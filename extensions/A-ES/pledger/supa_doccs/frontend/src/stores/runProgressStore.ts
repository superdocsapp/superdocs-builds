import { create } from "zustand";
import type { PipelineProgress, RunSummary } from "@/types/review";

interface RunProgressState {
  currentNode: string | null;
  completedNodes: string[];
  nodeStatus: "completed" | "skipped" | "error" | null;
  runStatus: "running" | "completed" | "failed" | "paused";
  runs: RunSummary[];
  selectedRunId: string | null;

  // Actions
  setProgress: (progress: PipelineProgress) => void;
  setRuns: (runs: RunSummary[]) => void;
  setSelectedRunId: (runId: string | null) => void;
  reset: () => void;
}

const initialState = {
  currentNode: null,
  completedNodes: [] as string[],
  nodeStatus: null as RunProgressState["nodeStatus"],
  runStatus: "running" as RunProgressState["runStatus"],
  runs: [] as RunSummary[],
  selectedRunId: null as string | null,
};

export const useRunProgressStore = create<RunProgressState>((set) => ({
  ...initialState,

  setProgress: (progress: PipelineProgress) =>
    set({
      currentNode: progress.current_node,
      completedNodes: progress.completed_nodes,
      nodeStatus: progress.node_status,
      runStatus: progress.run_status,
    }),

  setRuns: (runs: RunSummary[]) => set({ runs }),

  setSelectedRunId: (runId: string | null) => set({ selectedRunId: runId }),

  reset: () => set({ ...initialState }),
}));
