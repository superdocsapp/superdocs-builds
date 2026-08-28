import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useRunResume } from "./useRunResume";
import { useRunProgressStore } from "@/stores/runProgressStore";

vi.mock("@/services/approvalApi", () => ({
  resumeRun: vi.fn(),
  fetchRunProgress: vi.fn(),
}));

import { resumeRun, fetchRunProgress } from "@/services/approvalApi";

const mockResumeRun = vi.mocked(resumeRun);
const mockFetchRunProgress = vi.mocked(fetchRunProgress);

describe("useRunResume", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRunProgressStore.getState().reset();
  });

  it("starts with isResuming=false and no error", () => {
    const { result } = renderHook(() => useRunResume());
    expect(result.current.isResuming).toBe(false);
    expect(result.current.resumeError).toBeNull();
  });

  it("sets isResuming to true while in-flight", async () => {
    let resolveResume: () => void;
    mockResumeRun.mockReturnValue(
      new Promise((resolve) => {
        resolveResume = () => resolve(undefined);
      })
    );
    mockFetchRunProgress.mockResolvedValue({
      current_node: "ingest",
      completed_nodes: [],
      node_status: null,
      run_status: "running",
    });

    const { result } = renderHook(() => useRunResume());

    let promise: Promise<void>;
    act(() => {
      promise = result.current.handleResume("run-1");
    });

    expect(result.current.isResuming).toBe(true);

    await act(async () => {
      resolveResume!();
      await promise;
    });

    expect(result.current.isResuming).toBe(false);
  });

  it("on success: fetches progress and updates the store", async () => {
    mockResumeRun.mockResolvedValue(undefined);
    mockFetchRunProgress.mockResolvedValue({
      current_node: "extract_text",
      completed_nodes: ["ingest"],
      node_status: "completed",
      run_status: "running",
    });

    const { result } = renderHook(() => useRunResume());

    await act(async () => {
      await result.current.handleResume("run-1");
    });

    expect(mockResumeRun).toHaveBeenCalledWith("run-1");
    expect(mockFetchRunProgress).toHaveBeenCalledWith("run-1");

    const storeState = useRunProgressStore.getState();
    expect(storeState.currentNode).toBe("extract_text");
    expect(storeState.completedNodes).toEqual(["ingest"]);
    expect(storeState.runStatus).toBe("running");
  });

  it("on failure: sets resumeError and does not update store", async () => {
    mockResumeRun.mockRejectedValue(new Error("Server error"));

    const { result } = renderHook(() => useRunResume());

    await act(async () => {
      await result.current.handleResume("run-1");
    });

    expect(result.current.resumeError).toBe("Server error");
    expect(result.current.isResuming).toBe(false);

    // Store should remain at initial state
    const storeState = useRunProgressStore.getState();
    expect(storeState.currentNode).toBeNull();
    expect(storeState.runStatus).toBe("running");
  });

  it("clearResumeError resets the error state", async () => {
    mockResumeRun.mockRejectedValue(new Error("Oops"));

    const { result } = renderHook(() => useRunResume());

    await act(async () => {
      await result.current.handleResume("run-1");
    });

    expect(result.current.resumeError).toBe("Oops");

    act(() => {
      result.current.clearResumeError();
    });

    expect(result.current.resumeError).toBeNull();
  });

  it("on fetchRunProgress failure: sets resumeError", async () => {
    mockResumeRun.mockResolvedValue(undefined);
    mockFetchRunProgress.mockRejectedValue(new Error("Progress fetch failed"));

    const { result } = renderHook(() => useRunResume());

    await act(async () => {
      await result.current.handleResume("run-1");
    });

    expect(result.current.resumeError).toBe("Progress fetch failed");
    expect(result.current.isResuming).toBe(false);
  });
});
