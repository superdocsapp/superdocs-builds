import {test, expect} from '@playwright/test';

test('reviewer can inspect evidence, block export, restore it, and prepare the verified PDF', async ({page}) => {
  await page.goto('/');
  await expect(page.getByRole('heading', {name: '6/6 source spans'})).toBeVisible();
  await page.getByRole('button', {name: 'Reject SAFE-001'}).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', {name: '5/6 source spans'})).toBeVisible();
  await expect(page.getByLabel('Operator card page 1')).toContainText('Evidence excluded — restore this source span before release.');
  await expect(page.getByRole('region', {name: 'Manual evidence viewer'})).toBeVisible();
  const manualPreview = page.getByRole('img', {name: 'Manual page with SAFE-001 highlighted'});
  await expect(manualPreview).toBeVisible();
  await expect.poll(() => manualPreview.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
  await page.getByRole('button', {name: 'Verify this card'}).click();
  await expect(page.getByRole('alert')).toContainText('SAFE-001');
  await page.getByRole('button', {name: 'Include SAFE-001'}).click();
  await expect(page.getByLabel('Operator card page 1')).toContainText('Isolate electrical and pneumatic energy before clearing a jam.');
  await page.getByRole('button', {name: 'Verify this card'}).click();
  await expect(page.getByRole('button', {name: 'Prepare PDF'})).toBeVisible();
  await page.getByRole('button', {name: 'Prepare PDF'}).click();
  await expect(page.getByRole('link', {name: 'Download PDF ↓'})).toBeVisible();
  await expect(page.getByRole('region', {name: 'Export receipt'})).toContainText('2-page reviewed PDF prepared');
});

test('reviewer can run the actual 400-page scale check', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name: 'Run 400-page scale check'}).click();
  await expect(page.getByText('400 pages indexed')).toBeVisible();
  await expect(page.getByRole('link', {name: 'Open 400-page fixture ↗'})).toBeVisible();
});

test('safety-gap scenario changes the real preview state', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name: 'Run safety-gap scenario'}).click();
  await expect(page.getByLabel('Review progress')).toContainText('Protected gaps shown');
  await expect(page.getByRole('button', {name: 'Restore safety scenario'})).toBeVisible();
});
