import { test as base, expect, Page } from "@playwright/test";
import { setupAllMocks } from "./mockServer";
import {
  mockRuns,
  mockQueueResponse,
  mockProgressRunning,
} from "../fixtures/mockData";
import type {
  QueueListResponse,
  RunSummary,
  PipelineProgress,
  DecisionResponse,
} from "../../src/types/review";

/**
 * Extended test fixtures with pre-configured mock API data.
 * Tests can override any fixture by providing custom values.
 */
interface ReviewFixtures {
  queueData: QueueListResponse;
  runsData: RunSummary[];
  progressData: PipelineProgress;
  decisionHandler:
    | ((itemId: string, body: Record<string, unknown>) => {
        status: number;
        body: DecisionResponse | { error: string };
      })
    | undefined;
}

export const test = base.extend<ReviewFixtures>({
  queueData: [mockQueueResponse, { option: true }],
  runsData: [mockRuns, { option: true }],
  progressData: [mockProgressRunning, { option: true }],
  decisionHandler: [undefined, { option: true }],

  page: async (
    { page, queueData, runsData, progressData, decisionHandler },
    use
  ) => {
    await setupAllMocks(page, {
      queue: queueData,
      runs: runsData,
      progress: progressData,
      decisionHandler,
    });
    await use(page);
  },
});

export { expect };

/**
 * Navigate to the review page and wait for the initial data to load.
 */
export async function navigateToReview(page: Page): Promise<void> {
  await page.goto("/review");
  // Wait for the queue list to be rendered
  await page.waitForSelector("[role='listbox']", { timeout: 10_000 });
}
