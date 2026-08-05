import { expect, test } from '@playwright/test';

test('submits the target current-disaster question and renders a source-backed report', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Open assistant' }).click();
  await page
    .getByLabel('Question')
    .fill(
      'There was a recent earthquake in Japan. Please update me with the latest information about the damages in Japan.',
    );
  await page.getByRole('button', { name: 'Ask assistant' }).click();

  await expect(page.getByText('Ishikawa, Japan', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Situation summary' })).toBeVisible();
  await expect(page.getByText('Buildings damaged: 4.').first()).toBeVisible();
  await expect(page.getByRole('link', { name: /ReliefWeb fixture/ })).toBeVisible();
  await expect(page.getByText(/Retrieved:/)).toBeVisible();
});
