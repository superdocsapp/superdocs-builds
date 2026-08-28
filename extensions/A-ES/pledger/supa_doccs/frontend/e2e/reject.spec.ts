import { test, expect, navigateToReview } from "./helpers/setup";

/**
 * Playwright integration test: Reject flow with isolation verification.
 * Validates: Requirements 12.2
 *
 * Verifies that submitting a reject decision updates the target item to
 * "rejected" status while all other queue items remain unchanged.
 */
test.describe("Reject flow with isolation", () => {
  test("rejecting a pending item updates its status without affecting others", async ({
    page,
  }) => {
    await navigateToReview(page);

    // Wait for queue items to render
    const listbox = page.locator("[role='listbox']");
    await expect(listbox).toBeVisible();

    const items = listbox.locator("[role='option']");
    await expect(items).toHaveCount(6);

    // Record original statuses for all 6 items before the action.
    // Mock data order: item-001 (pending), item-002 (pending), item-003 (approved),
    // item-004 (pending), item-005 (rejected), item-006 (pending)
    const originalStatuses: string[] = [];
    for (let i = 0; i < 6; i++) {
      const statusText = await items.nth(i).locator("span.rounded-full").innerText();
      originalStatuses.push(statusText.trim());
    }

    // Verify expected initial state
    expect(originalStatuses[0]).toBe("pending");
    expect(originalStatuses[1]).toBe("pending");
    expect(originalStatuses[2]).toBe("approved");
    expect(originalStatuses[3]).toBe("pending");
    expect(originalStatuses[4]).toBe("rejected");
    expect(originalStatuses[5]).toBe("pending");

    // Click on item-002 (index 1) — a pending conflict item
    await items.nth(1).click();

    // Wait for detail panel to show the decision controls
    const justificationInput = page.locator(
      "textarea[aria-label='Decision justification']"
    );
    await expect(justificationInput).toBeVisible();

    // Enter justification text
    await justificationInput.fill(
      "Conflict is valid — LTV statements are irreconcilable."
    );

    // Click the Reject button
    const rejectButton = page.locator("button", { hasText: "Reject" });
    await expect(rejectButton).toBeEnabled();
    await rejectButton.click();

    // Verify: the rejected item (index 1) now shows "rejected" status
    await expect(items.nth(1).locator("span.rounded-full")).toHaveText(
      "rejected"
    );

    // Verify: all OTHER items retain their original statuses (isolation check)
    for (let i = 0; i < 6; i++) {
      if (i === 1) continue; // Skip the item we just rejected
      const currentStatus = await items
        .nth(i)
        .locator("span.rounded-full")
        .innerText();
      expect(currentStatus.trim()).toBe(originalStatuses[i]);
    }
  });
});
