import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  fetchQueue,
  fetchItem,
  submitDecision,
  fetchRuns,
  resumeRun,
  fetchRunProgress,
  ApiError,
} from "./approvalApi";

// Mock global fetch
const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  } as Response;
}

describe("approvalApi", () => {
  describe("fetchQueue", () => {
    it("returns queue data on success", async () => {
      const mockData = {
        run_id: "run-1",
        items: [],
        total: 0,
        pending: 0,
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(mockData));

      const result = await fetchQueue("run-1");
      expect(result).toEqual(mockData);
      expect(mockFetch).toHaveBeenCalledWith(
        "/approval/runs/run-1/queue",
        undefined
      );
    });

    it("throws not_found ApiError on 404", async () => {
      mockFetch.mockResolvedValue(jsonResponse({}, 404));

      await expect(fetchQueue("missing")).rejects.toThrow(ApiError);
      await expect(fetchQueue("missing")).rejects.toMatchObject({
        type: "not_found",
        status: 404,
      });
    });
  });

  describe("fetchItem", () => {
    it("returns item data on success", async () => {
      const mockItem = { id: "item-1", run_id: "run-1" };
      mockFetch.mockResolvedValueOnce(jsonResponse(mockItem));

      const result = await fetchItem("item-1");
      expect(result).toEqual(mockItem);
      expect(mockFetch).toHaveBeenCalledWith(
        "/approval/items/item-1",
        undefined
      );
    });

    it("throws conflict ApiError on 409", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}, 409));

      await expect(fetchItem("item-1")).rejects.toMatchObject({
        type: "conflict",
        status: 409,
      });
    });
  });

  describe("submitDecision", () => {
    it("posts decision and returns response on success", async () => {
      const mockResponse = {
        item_id: "item-1",
        decision: "approved",
        success: true,
        error: null,
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(mockResponse));

      const request = {
        decision: "approved" as const,
        reviewer_id: "reviewer-1",
        justification: "Looks good",
      };

      const result = await submitDecision("item-1", request);
      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        "/approval/items/item-1/decide",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
        }
      );
    });

    it("throws server_error ApiError on 500", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}, 500));

      const request = {
        decision: "rejected" as const,
        reviewer_id: "reviewer-1",
        justification: "Issues found",
      };

      await expect(submitDecision("item-1", request)).rejects.toMatchObject({
        type: "server_error",
        status: 500,
      });
    });
  });

  describe("fetchRuns", () => {
    it("returns array of runs on success", async () => {
      const mockRuns = [
        { id: "run-1", status: "running", started_at: "2024-01-01T00:00:00Z", ended_at: null },
      ];
      mockFetch.mockResolvedValueOnce(jsonResponse(mockRuns));

      const result = await fetchRuns();
      expect(result).toEqual(mockRuns);
      expect(mockFetch).toHaveBeenCalledWith("/runs", undefined);
    });
  });

  describe("resumeRun", () => {
    it("posts resume request on success", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ status: "running" }));

      const result = await resumeRun("run-1");
      expect(result).toEqual({ status: "running" });
      expect(mockFetch).toHaveBeenCalledWith("/runs/run-1/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
    });
  });

  describe("fetchRunProgress", () => {
    it("returns pipeline progress on success", async () => {
      const mockProgress = {
        current_node: "extract_claims",
        completed_nodes: ["ingest", "extract_text"],
        node_status: "completed",
        run_status: "running",
      };
      mockFetch.mockResolvedValueOnce(jsonResponse(mockProgress));

      const result = await fetchRunProgress("run-1");
      expect(result).toEqual(mockProgress);
      expect(mockFetch).toHaveBeenCalledWith("/runs/run-1/history", undefined);
    });
  });

  describe("error classification", () => {
    it("throws network_error on fetch failure", async () => {
      mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      await expect(fetchQueue("run-1")).rejects.toMatchObject({
        type: "network_error",
      });
    });

    it("throws server_error on 502", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}, 502));

      await expect(fetchRuns()).rejects.toMatchObject({
        type: "server_error",
        status: 502,
      });
    });

    it("throws server_error on 503", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}, 503));

      await expect(fetchRuns()).rejects.toMatchObject({
        type: "server_error",
        status: 503,
      });
    });

    it("classifies 4xx (non-404/409) as server_error", async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}, 422));

      await expect(fetchItem("item-1")).rejects.toMatchObject({
        type: "server_error",
        status: 422,
      });
    });
  });
});
