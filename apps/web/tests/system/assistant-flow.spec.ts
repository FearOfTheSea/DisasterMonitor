import { expect, test } from '@playwright/test';

test('submits a question and renders the deterministic fake-model response', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Open assistant' }).click();
  await page.getByLabel('Question').fill('What can I use this map for?');
  await page.getByRole('button', { name: 'Ask assistant' }).click();

  await expect(page.getByText('Deterministic system-test response.')).toBeVisible();
});
