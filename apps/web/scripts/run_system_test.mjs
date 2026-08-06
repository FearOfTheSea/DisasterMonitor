import { spawn } from 'node:child_process';

import { chromium } from '@playwright/test';

const stackProcess = spawn(
  'uv',
  ['run', '--project', '../api', 'python', '../../scripts/system_test_stack.py'],
  { cwd: process.cwd(), stdio: 'inherit' },
);

async function waitForApplication(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // The local stack is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function stopStack() {
  if (stackProcess.exitCode !== null) {
    return;
  }
  if (process.platform === 'win32') {
    spawn(
      'C:\\Windows\\System32\\taskkill.exe',
      ['/pid', String(stackProcess.pid), '/t', '/f'],
      {
        stdio: 'ignore',
        windowsHide: true,
      },
    ).unref();
  } else {
    stackProcess.kill('SIGTERM');
  }
}

try {
  await waitForApplication('http://127.0.0.1:4173/');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:4173/', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Open assistant' }).click();
  await page
    .getByLabel('Question')
    .fill(
      'Please give me the latest information about the earthquake in Japan on August 5, 2026.',
    );
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  await page.getByText('Ishikawa, Japan', { exact: true }).waitFor({ timeout: 30_000 });
  await page.getByRole('heading', { name: 'Situation summary' }).waitFor();
  await page.getByText('Buildings damaged: 4.').first().waitFor();
  await page.getByRole('link', { name: /ReliefWeb fixture/ }).waitFor();
  await page.getByText('Investigation details').click();
  await page.getByText(/Selected the source-backed event/).waitFor();
  for (const sentinel of [
    'Venezuela',
    'VENEZUELA-FOREIGN-EVIDENCE-SENTINEL',
    'TOKYO-UNRELATED-EVIDENCE-SENTINEL',
    'GENERAL-MODEL-SENTINEL',
  ]) {
    if (await page.getByText(new RegExp(sentinel, 'i')).count()) {
      throw new Error(`Unexpected decoy content rendered: ${sentinel}`);
    }
  }
  await page
    .getByText(/Retrieved:/)
    .first()
    .waitFor();
  await page
    .getByLabel('Question')
    .fill(
      'How many fatalities were reported for the August 5, 2026 earthquake in Japan?',
    );
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  await page.getByRole('heading', { name: 'Focused answer' }).waitFor();
  await page
    .getByText(/Fatalities: 2/)
    .first()
    .waitFor();
  await browser.close();
  console.log('System test passed: source-backed current-disaster report rendered.');
} finally {
  stopStack();
}
