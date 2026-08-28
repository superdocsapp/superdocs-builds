import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ReviewPage } from "./ReviewPage";
import { useQueueStore } from "@/stores/queueStore";
import { useRunProgressStore } from "@/stores/runProgressStore";
import type { RunSummary, QueueItem, QueueListResponse, PipelineProgress } from "@/types/review";

// ─── Mocks ───────────────────────────────────────────────────────────────────

vi.mock("@/services/approvalApi", () => ({
  fetchRuns: vi.fn(),
  fetchQueue: vi.fn(),
  fetchRunProgress: vi.fn(),
}));

vi.mock("@/services/decisionService", () => ({
  submitItemDecision: vi.fn(),
}));

import { fetchRuns, fetchQueue, fetchRunProgress } from "@/services/approvalApi";

const mockFetchRuns = vi.mocked(fetchRuns);
const mockFetchQueue = vi.mocked(fetchQueue);
const mockFetchRunProgress = vi.mocked(fetchRunProgress);

// ─── Test Data ───────────────────────────────────────────────────────────────

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-1",
    status: "running",
    started_at: "2024-01-01T00:00:00Z",
    ended_at: null,
    ...overrides,
  };
}

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Test finding summary",
      details: {},
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-01T00:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
    ...overrides,
  };
}

const defaultQueueResponse: QueueListResponse = {
  run_id: "run-1",
  items: [makeItem({ id: "item-1" }), makeItem({ id: "item-2", item_type: "conflict" })],
  total: 2,
  pending: 2,
};

const defaultProgressResponse: PipelineProgress = {
  current_node: "extract_claims",
  completed_nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"],
  node_status: "completed",
  run_status: "running",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function renderReviewPage() {
  return render(
    <MemoryRouter>
      <ReviewPage />
    </MemoryRouter>
  );
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("ReviewPage Integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset Zustand stores between tests
    useQueueStore.setState(useQueueStore.getInitialState());
    useRunProgressStore.setState({
      currentNode: null,
      completedNodes: [],
      nodeStatus: null,
      runStatus: "running",
      runs: [],
      selectedRunId: null,
    });

    // Default mock implementations
    mockFetchRuns.mockResolvedValue([makeRun({ id: "run-1" }), makeRun({ id: "run-2" })]);
    mockFetchQueue.mockResolvedValue(defaultQueueResponse);
    mockFetchRunProgress.mockResolvedValue(defaultProgressResponse);
  });

  describe("Renders all sub-components", () => {
    it("renders TopBar with run selector", async () => {
      renderReviewPage();

      // TopBar contains the RunSelector with aria-label "Select pipeline run"
      await waitFor(() => {
        expect(
          screen.getByLabelText("Select pipeline run")
        ).toBeInTheDocument();
      });
    });

    it("renders ProgressStepper with pipeline progress list", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(
          screen.getByRole("list", { name: "Pipeline progress" })
        ).toBeInTheDocument();
      });
    });

    it("renders MasterDetail with approval queue listbox", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(
          screen.getByRole("listbox", { name: "Approval queue items" })
        ).toBeInTheDocument();
      });
    });

    it("fetches runs on mount and auto-selects the first run", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(mockFetchRuns).toHaveBeenCalledTimes(1);
      });

      // Polling should start with the first run, triggering fetchQueue
      await waitFor(() => {
        expect(mockFetchQueue).toHaveBeenCalledWith("run-1");
      });
    });
  });

  describe("Run switching resets queue and refetches", () => {
    it("resets queue store and fetches new data when a different run is selected", async () => {
      const user = userEvent.setup();

      // Start with two runs available
      const runs = [makeRun({ id: "run-1" }), makeRun({ id: "run-2" })];
      mockFetchRuns.mockResolvedValue(runs);

      // Return different queue data for run-2
      const run2Queue: QueueListResponse = {
        run_id: "run-2",
        items: [makeItem({ id: "item-3", run_id: "run-2" })],
        total: 1,
        pending: 1,
      };
      mockFetchQueue.mockImplementation(async (runId: string) => {
        if (runId === "run-2") return run2Queue;
        return defaultQueueResponse;
      });

      renderReviewPage();

      // Wait for initial load to complete
      await waitFor(() => {
        expect(screen.getByLabelText("Select pipeline run")).toBeInTheDocument();
      });

      // Verify the queue store was reset before loading new run
      // We spy on reset by checking the store state changes
      const resetSpy = vi.fn();
      const originalReset = useQueueStore.getState().reset;
      useQueueStore.setState({
        reset: () => {
          resetSpy();
          originalReset();
        },
      });

      // Click the run selector to open the dropdown
      const trigger = screen.getByLabelText("Select pipeline run");
      await user.click(trigger);

      // Wait for dropdown content to appear and select run-2
      await waitFor(() => {
        const run2Option = screen.getByText("run-2");
        expect(run2Option).toBeInTheDocument();
      });

      const run2Option = screen.getByText("run-2");
      await user.click(run2Option);

      // Verify the queue reset was called
      expect(resetSpy).toHaveBeenCalled();

      // Verify new data is fetched for run-2
      await waitFor(() => {
        expect(mockFetchQueue).toHaveBeenCalledWith("run-2");
      });
    });
  });

  describe("Responsive layout", () => {
    it("MasterDetail has correct responsive CSS classes for desktop flex-row", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(screen.getByRole("listbox", { name: "Approval queue items" })).toBeInTheDocument();
      });

      // The MasterDetail wrapper should contain md:flex-row class
      const masterDetailContainer = screen.getByRole("listbox", { name: "Approval queue items" })
        .closest(".flex.h-full.w-full");
      expect(masterDetailContainer).toBeInTheDocument();
      expect(masterDetailContainer).toHaveClass("md:flex-row");
    });

    it("list panel has md:w-2/5 class for 40% width on desktop", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(screen.getByRole("listbox", { name: "Approval queue items" })).toBeInTheDocument();
      });

      // The list panel container should have md:w-2/5
      const listbox = screen.getByRole("listbox", { name: "Approval queue items" });
      const listPanel = listbox.closest(".md\\:w-2\\/5");
      expect(listPanel).toBeInTheDocument();
    });

    it("detail panel has md:flex-1 class for flexible width on desktop", async () => {
      renderReviewPage();

      await waitFor(() => {
        expect(screen.getByRole("listbox", { name: "Approval queue items" })).toBeInTheDocument();
      });

      // The detail panel is the sibling with md:flex-1
      const listbox = screen.getByRole("listbox", { name: "Approval queue items" });
      const masterDetail = listbox.closest(".flex.h-full.w-full");
      const detailPanel = masterDetail?.querySelector(".md\\:flex-1");
      expect(detailPanel).toBeInTheDocument();
    });
  });
});
