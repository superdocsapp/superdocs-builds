import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe('Knowledge-base Freshness Sweeper — Headed User E2E Journey', () => {
  const screenshotsDir = path.resolve(__dirname, '../docs/screenshots');

  test.beforeAll(() => {
    if (!fs.existsSync(screenshotsDir)) {
      fs.mkdirSync(screenshotsDir, { recursive: true });
    }
  });

  test('Complete Knowledge Manager Workflow (Sweep -> Evidence -> Surgical Review -> Approve -> Governance)', async ({ page }) => {
    page.on('console', msg => console.log('BROWSER CONSOLE:', msg.type(), msg.text()));
    page.on('pageerror', err => console.log('BROWSER PAGE ERROR:', err.message));

    // 1. Visit the dashboard
    await page.goto('/');
    await page.waitForSelector('h1', { timeout: 15000 });

    // Verify Title & Branding
    await expect(page.locator('h1')).toContainText('Knowledge-base Freshness Sweeper');
    await expect(page.getByText('Task 2.3')).toBeVisible();

    // 2. Theme Toggle Flow
    await page.screenshot({ path: path.join(screenshotsDir, '01_dashboard_dark.png') });
    
    const themeBtn = page.getByTitle('Toggle theme');
    await themeBtn.click();
    await page.waitForTimeout(300);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.screenshot({ path: path.join(screenshotsDir, '02_dashboard_light.png') });

    // Switch back to dark for standard viewing
    await themeBtn.click();
    await page.waitForTimeout(300);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    // 3. Trigger Small-Sample Mode (5 Articles)
    const sampleBtn = page.getByRole('button', { name: 'Sample (5)' });
    await sampleBtn.click();
    await page.waitForTimeout(400);

    // 4. Trigger Full Corpus Sweep (32 Articles)
    const fullSweepBtn = page.getByRole('button', { name: 'Run Full Sweep' });
    await fullSweepBtn.click();
    await page.waitForTimeout(500);

    // Verify Metric Cards
    await expect(page.getByText('Scanned Articles')).toBeVisible();
    await expect(page.getByText('Stale / Affected')).toBeVisible();
    await expect(page.getByText('Pending Proposals')).toBeVisible();
    await expect(page.getByText('Stale Screenshots')).toBeVisible();
    await expect(page.getByText('Could Not Assess', { exact: true })).toBeVisible();
    await expect(page.getByText('$0.00')).toBeVisible();

    // 5. Inspect Surgical Review Queue
    await page.screenshot({ path: path.join(screenshotsDir, '03_surgical_review_queue.png') });
    
    // Select first proposal (art-001)
    await page.getByText('API Rate Limits and Quotas').first().click();
    await page.waitForTimeout(200);

    // Verify Evidence & Diff
    await expect(page.getByText('Verified Sentence-Level Evidence:')).toBeVisible();
    await expect(page.getByText('On the Pro plan, users are allocated 10,000 API calls per month.').first()).toBeVisible();
    await expect(page.getByText('Surgical Sentence Diff')).toBeVisible();

    // Approve the proposal
    const approveBtn = page.getByRole('button', { name: 'Approve & Patch' });
    await expect(approveBtn).toBeVisible();
    await approveBtn.click();
    await page.waitForTimeout(400);

    // Verify Proposal transitioned to APPROVED
    await expect(page.getByText('APPROVED').first()).toBeVisible();
    await page.screenshot({ path: path.join(screenshotsDir, '04_proposal_approved.png') });

    // 6. Test Knowledge Base Explorer Tab
    const articlesTab = page.getByRole('button', { name: /Knowledge Base Explorer/i });
    await articlesTab.click();
    await page.waitForTimeout(300);

    // Search for articles
    const searchInput = page.getByPlaceholder('Search articles by title, content, or category...');
    await searchInput.fill('API');
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(screenshotsDir, '05_kb_search_filter.png') });

    // Clear search
    await searchInput.fill('');
    await page.waitForTimeout(200);

    // 7. Test Screenshot Staleness Tab
    const screenshotTab = page.getByRole('button', { name: /Screenshot Staleness/i });
    await screenshotTab.click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Screenshot ID: ss-003-1')).toBeVisible();
    await expect(page.getByText('Mismatched UI Labels in Image OCR:').first()).toBeVisible();
    await page.screenshot({ path: path.join(screenshotsDir, '06_screenshot_staleness.png') });

    // 8. Test Could Not Assess Tab
    const cnaTab = page.getByRole('button', { name: /Could Not Assess/i });
    await cnaTab.click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Honest Uncertainty Policy')).toBeVisible();
    await expect(page.getByText('Custom Enterprise Contract Provisions')).toBeVisible();
    await page.screenshot({ path: path.join(screenshotsDir, '07_could_not_assess_disclosures.png') });

    // 9. Test Evaluation Benchmark Tab
    const benchmarkTab = page.getByRole('button', { name: /Evaluation Benchmark/i });
    await benchmarkTab.click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Seeded Evaluation Corpus Benchmark Results')).toBeVisible();
    await expect(page.getByText('100.0%').first()).toBeVisible();
    await expect(page.getByText('Confusion Matrix (32 Fixture Articles)')).toBeVisible();
    await page.screenshot({ path: path.join(screenshotsDir, '08_benchmark_confusion_matrix.png') });

    // 10. Test Budget Guard Tab
    const budgetTab = page.getByRole('button', { name: /Budget Guard/i });
    await budgetTab.click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Budget Guard Configuration')).toBeVisible();
    await page.screenshot({ path: path.join(screenshotsDir, '09_budget_guard.png') });
  });
});
