import { test, expect } from "@playwright/test";

test.describe("Theme Switcher (Light / Dark Mode)", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("superdocs_bates_theme", "dark");
    });
  });

  test("Theme switcher toggles between Light Mode and Dark Mode and persists", async ({ page }) => {
    // Navigate to application
    await page.goto("http://localhost:5173");
    await page.waitForLoadState("networkidle");

    // Locate the navbar toggle button by ID
    const navbarToggle = page.locator("#navbar-theme-toggle");
    await expect(navbarToggle).toBeVisible();

    const html = page.locator("html");

    // Verify initial dark mode
    await expect(html).toHaveClass(/dark/);
    expect(await page.evaluate(() => localStorage.getItem("superdocs_bates_theme"))).toBe("dark");

    // Click toggle to switch to Light Mode
    await navbarToggle.click();
    await page.waitForTimeout(400);

    // Expect HTML class to be light
    await expect(html).toHaveClass(/light/);
    expect(await page.evaluate(() => localStorage.getItem("superdocs_bates_theme"))).toBe("light");

    // Take screenshot in Light Mode
    await page.screenshot({ path: "test-results/light-mode.png", fullPage: true });

    // Navigate to Settings in Light Mode
    await page.getByRole("link", { name: /system diagnostics/i }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: "test-results/settings-light.png", fullPage: true });

    // Switch back to Dark Mode via navbar toggle
    await navbarToggle.click();
    await page.waitForTimeout(400);

    // Expect HTML class to be dark
    await expect(html).toHaveClass(/dark/);
    expect(await page.evaluate(() => localStorage.getItem("superdocs_bates_theme"))).toBe("dark");

    // Take screenshot in Dark Mode
    await page.screenshot({ path: "test-results/dark-mode.png", fullPage: true });
  });
});
