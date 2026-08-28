import { test, expect, navigateToReview } from "./helpers/setup";

/**
 * Playwright integration test for the approve flow.
 * Validates: Requirements 12.1
 *
 * Steps:
 * 1. Navigate to /review and wait for queue to load
 * 2. Select a pending item (item-001)
 * 3. Verify the detail panel shows item payload
 * 4. Enter justification text
 * 5. Click Approve
 * 6. Verify item status updates to approved in detail panel and queue list
 */
test.describe("Approve Flow", () => {
  test("approving a pending item updates status to approved", async ({
    page,
  }) => {
    // Step 1: Navigate to /review and wait for initial load
    await navigateToReview(page);

    // Step 2: Wait for queue items to render and click on a pending item (item-001)
    const queueItems = page.getByRole("option");
    await expect(queueItems.first()).toBeVisible();

    // Find and click the pending item-001 (finding about capital adequacy)
    const pendingItem = queueItems.filter({ hasText: "capital adequacy" });
    await pendingItem.click();

    // Step 3: Verify the detail panel displays the item payload
    const detailPanel = page.getByRole("region", { name: /detail/i });
    await expect(detailPanel).toBeVisible();
    await expect(
      detailPanel.getByText(/capital adequacy/i)
    ).toBeVisible();

    // Step 4: Enter justification text in the textarea
    const justificationInput = page.getByLabel("Decision justification");
    await expect(justificationInput).toBeVisible();
    await justificationInput.fill(
      "Reviewed and confirmed compliance with Section 4.2 requirements."
    );

    // Step 5: Click the Approve button
    const approveButton = page.getByRole("button", { name: /approve/i });
    await expect(approveButton).toBeEnabled();
    await approveButton.click();

    // Step 6: Verify the item status updates to approved
    // Check detail panel shows approved status
    await expect(
      detailPanel.getByText(/approved/i)
    ).toBeVisible();

    // Check queue list item also shows approved status
    const queueItemInList = queueItems.filter({
      hasText: "capital adequacy",
    });
    await expect(queueItemInList.getByText(/approved/i)).toBeVisible();
  });
});
