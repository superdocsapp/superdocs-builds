import { test, expect, navigateToReview } from "./helpers/setup";
import {
  mockProgressPaused,
  mockProgressRunning,
  mockQueueItems,
  mockQueueResponse,
} from "./fixtures/mockData";
import type { QueueListResponse } from "../src/types/review";

/**
 * Playwright integration test for the kill/restart resume path.
 * Validates: Requirements 12.3
 *
 * Simulates a backend restart scenario by:
 * 1. Loading with paused pipeline progress
 * 2. Approving a pending item
 * 3. Simulating connection loss (network error on queue API)
 * 4. Restoring the backend with the approved item persisted
 * 5. Verifying decisions persist and progress stepper reflects resumed state
 */
test.describe("Kill/Restart Resume Path", () => {
  // Override progressData to use paused state so the run shows as "paused"
  test.use({ progressData: mockProgressPaused });

  test("previously submitted decisions persist after backend restart and progress stepper reflects resumed state", async ({
    page,
  }) => {
    // Step 1: Navigate to /review with paused progress
    await navigateToReview(page);

    // Verify the progress stepper shows "Stay-Alive" stage as in-progress (paused at human_review)
    const progressStepper = page.getByRole("list", {
      name: /pipeline progress/i,
    });
    await expect(progressStepper).toBeVisible();

    // The "Stay-Alive" stage should be "In progress" since current_node is "human_review"
    const stayAliveStage = page.getByRole("listitem", {
      name: /Stay-Alive.*In progress/i,
    });
    await expect(stayAliveStage).toBeVisible();

    // Step 2: Approve a pending item (item-001) to simulate a submitted decision
    const queueItems = page.getByRole("option");
    await expect(queueItems.first()).toBeVisible();

    // Click the pending finding item (capital adequacy)
    const pendingItem = queueItems.filter({ hasText: "capital adequacy" });
    await pendingItem.click();

    // Enter justification and approve
    const justificationInput = page.getByLabel("Decision justification");
    await expect(justificationInput).toBeVisible();
    await justificationInput.fill("Confirmed compliance per Section 4.2.");

    const approveButton = page.getByRole("button", { name: /approve/i });
    await expect(approveButton).toBeEnabled();
    await approveButton.click();

    // Verify item shows approved status in the queue list
    await expect(
      pendingItem.getByText(/approved/i)
    ).toBeVisible();

    // Step 3: Simulate backend restart — make queue API return network error
    await page.unroute("**/approval/runs/*/queue");
    await page.route("**/approval/runs/*/queue", (route) => {
      route.abort("connectionrefused");
    });

    // Wait for the connection lost banner to appear (next poll cycle will fail)
    const connectionBanner = page.getByRole("alert");
    await expect(connectionBanner).toBeVisible({ timeout: 15_000 });
    await expect(
      connectionBanner.getByText(/connection lost/i)
    ).toBeVisible();

    // Step 4: "Restart" the backend — restore the queue API with the approved item persisted
    const updatedItems = mockQueueItems.map((item) =>
      item.id === "item-001"
        ? {
            ...item,
            status: "approved" as const,
            decision: "approved" as const,
            decided_at: new Date().toISOString(),
            reviewer_id: "current-user",
            justification: "Confirmed compliance per Section 4.2.",
          }
        : item
    );
    const updatedQueueResponse: QueueListResponse = {
      run_id: "run-001",
      items: updatedItems,
      total: updatedItems.length,
      pending: updatedItems.filter((i) => i.status === "pending").length,
    };

    await page.unroute("**/approval/runs/*/queue");
    await page.route("**/approval/runs/*/queue", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(updatedQueueResponse),
      });
    });

    // Also update the progress endpoint to return "running" state (post-resume)
    await page.unroute("**/runs/*/history");
    await page.route("**/runs/*/history", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockProgressRunning),
      });
    });

    // Step 5: Verify the connection lost banner disappears
    await expect(connectionBanner).toBeHidden({ timeout: 15_000 });

    // Step 6: Verify the previously approved item is still approved (decision persisted)
    const approvedItem = page.getByRole("option").filter({
      hasText: "capital adequacy",
    });
    await expect(approvedItem.getByText(/approved/i)).toBeVisible();

    // Step 7: Verify the progress stepper reflects the resumed/running state
    // After re-routing history to mockProgressRunning, the "Examine" stage should show "In progress"
    // (current_node is "match_rules_against_sources" which is in Examine stage)
    const examineStage = page.getByRole("listitem", {
      name: /Examine.*In progress/i,
    });
    await expect(examineStage).toBeVisible({ timeout: 15_000 });

    // The "Understand" stage should be complete
    const understandStage = page.getByRole("listitem", {
      name: /Understand.*Complete/i,
    });
    await expect(understandStage).toBeVisible();
  });
});
