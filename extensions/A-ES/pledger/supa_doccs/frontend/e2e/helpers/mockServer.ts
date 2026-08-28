import { Page } from "@playwright/test";
import type {
  QueueListResponse,
  QueueItem,
  DecisionResponse,
  PipelineProgress,
  RunSummary,
} from "../../src/types/review";

/**
 * Intercepts GET /approval/runs/{run_id}/queue and returns mock queue data.
 */
export async function mockQueueApi(
  page: Page,
  data: QueueListResponse
): Promise<void> {
  await page.route("**/approval/runs/*/queue", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}

/**
 * Intercepts GET /approval/items/{item_id} and returns the matching item
 * from the provided list, or 404 if not found.
 */
export async function mockItemApi(
  page: Page,
  items: QueueItem[]
): Promise<void> {
  await page.route("**/approval/items/*", (route, request) => {
    if (request.method() !== "GET") {
      route.fallback();
      return;
    }
    const url = request.url();
    const itemId = url.split("/approval/items/")[1]?.split("/")[0]?.split("?")[0];
    const item = items.find((i) => i.id === itemId);

    if (item) {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(item),
      });
    } else {
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ error: "Item not found" }),
      });
    }
  });
}

/**
 * Intercepts POST /approval/items/{item_id}/decide and returns a success response.
 * Optionally accepts a custom handler for simulating errors (409, 500, etc.).
 */
export async function mockDecisionApi(
  page: Page,
  handler?: (itemId: string, body: Record<string, unknown>) => {
    status: number;
    body: DecisionResponse | { error: string };
  }
): Promise<void> {
  await page.route("**/approval/items/*/decide", async (route, request) => {
    if (request.method() !== "POST") {
      route.fallback();
      return;
    }

    const url = request.url();
    const itemId = url.split("/approval/items/")[1]?.split("/decide")[0];
    const body = JSON.parse(request.postData() || "{}");

    if (handler) {
      const result = handler(itemId, body);
      route.fulfill({
        status: result.status,
        contentType: "application/json",
        body: JSON.stringify(result.body),
      });
    } else {
      const response: DecisionResponse = {
        item_id: itemId,
        decision: body.decision,
        success: true,
        error: null,
      };
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(response),
      });
    }
  });
}

/**
 * Intercepts the runs endpoint and returns mock run summaries.
 */
export async function mockRunsApi(
  page: Page,
  data: RunSummary[]
): Promise<void> {
  await page.route("**/runs", (route, request) => {
    if (request.method() === "GET" || request.method() === "POST") {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    } else {
      route.fallback();
    }
  });
}

/**
 * Intercepts GET /runs/{run_id}/history and returns mock pipeline progress data.
 */
export async function mockProgressApi(
  page: Page,
  data: PipelineProgress
): Promise<void> {
  await page.route("**/runs/*/history", (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}

/**
 * Intercepts POST /runs/{run_id}/resume and returns a success response
 * with updated progress data.
 */
export async function mockResumeApi(
  page: Page,
  progressAfterResume?: PipelineProgress
): Promise<void> {
  await page.route("**/runs/*/resume", (route, request) => {
    if (request.method() !== "POST") {
      route.fallback();
      return;
    }

    const response = progressAfterResume ?? {
      current_node: "human_review",
      completed_nodes: [
        "ingest",
        "extract_text",
        "classify_document",
        "chunk",
        "embed",
        "extract_claims",
        "match_rules",
        "match_rules_against_sources",
        "merge_findings",
        "score_confidence",
        "route_to_queue",
      ],
      node_status: "completed",
      run_status: "running",
    };

    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(response),
    });
  });
}

/**
 * Sets up all mock API routes with the provided data.
 * Convenience function for common test setup.
 */
export async function setupAllMocks(
  page: Page,
  options: {
    queue: QueueListResponse;
    runs: RunSummary[];
    progress: PipelineProgress;
    decisionHandler?: (itemId: string, body: Record<string, unknown>) => {
      status: number;
      body: DecisionResponse | { error: string };
    };
  }
): Promise<void> {
  await mockQueueApi(page, options.queue);
  await mockItemApi(page, options.queue.items);
  await mockRunsApi(page, options.runs);
  await mockProgressApi(page, options.progress);
  await mockDecisionApi(page, options.decisionHandler);
  await mockResumeApi(page);
}
