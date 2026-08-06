import { expect, test } from '@playwright/test';

test('submits the target current-disaster question and renders a source-backed report', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Open assistant' }).click();
  await page
    .getByLabel('Question')
    .fill(
      'Please give me the latest information about the earthquake in Japan on August 5, 2026.',
    );
  await page.getByRole('button', { name: 'Ask assistant' }).click();

  await expect(page.getByText('Ishikawa, Japan', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Situation summary' })).toBeVisible();
  await expect(page.getByText('Buildings damaged: 4.').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /ReliefWeb fixture/ })).toBeVisible();
  await expect(page.getByText(/Retrieved:/)).toBeVisible();
  await page.getByText('Investigation details').click();
  await expect(page.getByText(/Selected the source-backed event/)).toBeVisible();
  await expect(page.getByText(/Venezuela/i)).toHaveCount(0);
  await expect(page.getByText(/VENEZUELA-FOREIGN-EVIDENCE-SENTINEL/i)).toHaveCount(0);
  await expect(page.getByText(/TOKYO-UNRELATED-EVIDENCE-SENTINEL/i)).toHaveCount(0);
  await expect(page.getByText(/GENERAL-MODEL-SENTINEL/i)).toHaveCount(0);
});
