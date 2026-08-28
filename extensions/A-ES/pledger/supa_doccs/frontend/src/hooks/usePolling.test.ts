import { renderHook, act } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import { usePolling } from "./usePolling";
import type { PollingConfig } from "./usePolling";
import * as approvalApi from "@/services/approvalApi";
import { useQueueStore } from "@/stores/queueStore";
import { useRunProgressStore } from "@/stores/runProgressStore";
import type { QueueListResponse, PipelineProgress } from "@/types/review";

vi.mock("@/services/approvalApi", () => ({
  fetchQueue: vi.fn(),
  fetchRunProgress: vi.fn(),
}));

const mockQueueResponse: QueueListResponse = {
  run_id: "run-1",
  items: [
    {
      id: "item-1",
      run_id: "run-1",
      item_type: "finding",
      payload: { summary: "Test finding", details: {}, source_citations: [] },
      status: "pending",
      queued_at: "2024-01-01T00:00:00Z",
      decided_at: null,
      decision: null,
      reviewer_id: null,
      justification: null,
    },
  ],
  total: 1,
  pending: 1,
};

const mockProgressResponse: PipelineProgress = {
  current_node: "extract_claims",
  completed_nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"],
  node_status: "completed",
  run_status: "running",
};

describe("usePolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(approvalApi.fetchQueue).mockResolvedValue(mockQueueResponse);
    vi.mocked(approvalApi.fetchRunProgress).mockResolvedValue(mockProgressResponse);
    useQueueStore.getState().reset();
    useRunProgressStore.getState().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("should not poll when runId is null", () => {
    const config: PollingConfig = { intervalMs: 10_000, enabled: true, runId: null };
    renderHook(() => usePolling(config));

    expect(approvalApi.fetchQueue).not.toHaveBeenCalled();
    expect(approvalApi.fetchRunProgress).not.toHaveBeenCalled();
  });

  it("should not poll when enabled is false", () => {
    const config: PollingConfig = { intervalMs: 10_000, enabled: false, runId: "run-1" };
    renderHook(() => usePolling(config));

    expect(approvalApi.fetchQueue).not.toHaveBeenCalled();
    expect(approvalApi.fetchRunProgress).not.toHaveBeenCalled();
  });

  it("should fetch immediately when enabled with a runId", async () => {
    const config: PollingConfig = { intervalMs: 10_000, enabled: true, runId: "run-1" };
    renderHook(() => usePolling(config));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(approvalApi.fetchQueue).toHaveBeenCalledWith("run-1");
    expect(approvalApi.fetchRunProgress).toHaveBeenCalledWith("run-1");
  });

  it("should merge fetched data into stores", async () => {
    const config: PollingConfig = { intervalMs: 10_000, enabled: true, runId: "run-1" };
    renderHook(() => usePolling(config));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const queueState = useQueueStore.getState();
    expect(queueState.items).toHaveLength(1);
    expect(queueState.total).toBe(1);
    expect(queueState.pending).toBe(1);

    const progressState = useRunProgressStore.getState();
    expect(progressState.currentNode).toBe("extract_claims");
    expect(progressState.completedNodes).toHaveLength(5);
    expect(progressState.runStatus).toBe("running");
  });

  it("should update lastFetchedAt on successful fetch", async () => {
    const config: PollingConfig = { intervalMs: 10_000, enabled: true, runId: "run-1" };
    const { result } = renderHook(() => usePolling(config));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.lastFetchedAt).toBeInstanceOf(Date);
    expect(result.current.error).toBeNull();
    expect(result.current.connectionLost).toBe(false);
  });

  it("should poll at the configured interval", async () => {
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    renderHook(() => usePolling(config));

    // Initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);

    // After one interval
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(2);

    // After another interval
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(3);
  });

  it("should set connectionLost on network error and preserve local state", async () => {
    // First fetch succeeds to populate stores
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    const { result } = renderHook(() => usePolling(config));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.connectionLost).toBe(false);
    expect(useQueueStore.getState().items).toHaveLength(1);

    // Now make fetch fail
    vi.mocked(approvalApi.fetchQueue).mockRejectedValue(new Error("Network error"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(result.current.connectionLost).toBe(true);
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("Network error");

    // Local state should be preserved
    expect(useQueueStore.getState().items).toHaveLength(1);
  });

  it("should clear connectionLost on successful fetch after error", async () => {
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    const { result } = renderHook(() => usePolling(config));

    // Initial fetch succeeds
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Next fetch fails
    vi.mocked(approvalApi.fetchQueue).mockRejectedValueOnce(new Error("Network error"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(result.current.connectionLost).toBe(true);

    // Restore mock and next fetch succeeds
    vi.mocked(approvalApi.fetchQueue).mockResolvedValue(mockQueueResponse);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(result.current.connectionLost).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("should pause polling when document becomes hidden", async () => {
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    renderHook(() => usePolling(config));

    // Initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);

    // Simulate tab becoming hidden
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Advance timers — should NOT fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);

    // Restore visibility
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
  });

  it("should resume with immediate fetch when document becomes visible", async () => {
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    renderHook(() => usePolling(config));

    // Initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);

    // Simulate tab hidden
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Simulate tab visible again
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });

    // Should have fetched again immediately
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(2);
  });

  it("should stop polling on unmount", async () => {
    const config: PollingConfig = { intervalMs: 5_000, enabled: true, runId: "run-1" };
    const { unmount } = renderHook(() => usePolling(config));

    // Initial fetch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);

    unmount();

    // Advance timers — should NOT fetch anymore
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(approvalApi.fetchQueue).toHaveBeenCalledTimes(1);
  });
});
