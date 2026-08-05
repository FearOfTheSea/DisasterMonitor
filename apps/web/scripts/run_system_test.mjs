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
  await page.getByLabel('Question').fill('What can I use this map for?');
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  await page
    .getByText('Deterministic system-test response.')
    .waitFor({ timeout: 30_000 });
  await browser.close();
  console.log('System test passed: fake backend response rendered in the Next.js UI.');
} finally {
  stopStack();
}
