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
  await waitForApplication('http://127.0.0.1:8787/api/v1/health');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:4173/', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Active incidents monitoring').waitFor();
  const incidentFixtures = [
    {
      coverageLabel: 'Earthquake',
      location: 'Aleutian earthquake fixture',
      focusedCoordinate: /52\.00,\s*-170\.00/,
    },
    {
      coverageLabel: 'Flood',
      location: 'Lower Mekong flood fixture',
      focusedCoordinate: /15\.00,\s*105\.00/,
      coverageState: 'Degraded',
    },
    {
      coverageLabel: 'Wildfire',
      location: 'Equatorial wildfire perimeter fixture',
      focusedCoordinate: /0\.00,\s*-120\.00/,
    },
    {
      coverageLabel: 'Landslide',
      location: 'Taiwan landslide fixture',
      focusedCoordinate: /23\.50,\s*121\.00/,
    },
    {
      coverageLabel: 'Tropical cyclone',
      location: 'Western Pacific cyclone track fixture',
      focusedCoordinate: /20\.00,\s*150\.00/,
    },
    {
      coverageLabel: 'Volcanic eruption',
      location: 'East African volcanic eruption fixture',
      focusedCoordinate: /-3\.00,\s*36\.00/,
    },
  ];
  for (const fixture of incidentFixtures) {
    await page
      .getByText(fixture.location, { exact: true })
      .waitFor({ timeout: 30_000 });
    const coverage = page
      .getByTestId('incident-coverage')
      .filter({ hasText: fixture.coverageLabel });
    await coverage.getByText(fixture.coverageLabel, { exact: true }).waitFor();
    await coverage
      .getByText(fixture.coverageState ?? 'Events found', { exact: true })
      .waitFor();
  }
  await page
    .getByRole('button', { name: 'Focus Lower Mekong flood fixture on map' })
    .getByText('estimated', { exact: true })
    .waitFor();
  await page
    .getByText('Flood fixture coverage is intentionally degraded.', { exact: true })
    .waitFor();
  if (await page.getByRole('heading', { name: 'Map assistant' }).count()) {
    throw new Error('The assistant opened before the Active Incidents workflow.');
  }
  for (const fixture of incidentFixtures) {
    const button = page.getByRole('button', {
      name: `Focus ${fixture.location} on map`,
    });
    await button.click();
    await page.locator('.map-overlay').getByText(fixture.focusedCoordinate).waitFor();
    if ((await button.getAttribute('aria-pressed')) !== 'true') {
      throw new Error(`Incident selection did not remain on ${fixture.location}.`);
    }
  }
  await page.getByRole('button', { name: 'Evidence operations' }).click();
  await page.getByRole('heading', { name: 'Incident watches' }).waitFor();
  await page.getByLabel('Watch disaster').selectOption('wildfire');
  await page.getByLabel('Watch scope').selectOption('worldwide');
  const createWatchResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/incident-watches') &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Create watch' }).click();
  if (!(await createWatchResponse).ok()) {
    throw new Error('The Incident Watch create request failed.');
  }
  const watchDeadline = Date.now() + 30_000;
  let scheduledAlertVisible = false;
  while (Date.now() < watchDeadline) {
    const response = await page.request.get(
      'http://127.0.0.1:8787/api/v1/incident-watches',
    );
    const watches = await response.json();
    if (
      watches.some(
        (watch) => watch.disaster === 'wildfire' && watch.unread_change_count === 1,
      )
    ) {
      scheduledAlertVisible = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!scheduledAlertVisible) {
    throw new Error('The scheduled Incident Watch refresh did not emit an alert.');
  }
  await page.getByRole('button', { name: 'Refresh watches' }).click();
  const watchCard = page
    .locator('.incident-watch-card')
    .filter({ hasText: 'Worldwide' });
  await watchCard.getByText('Wildfire', { exact: true }).waitFor();
  await watchCard.getByText('1 unread', { exact: true }).waitFor();
  await watchCard.getByRole('button', { name: 'Show timeline for Worldwide' }).click();
  await page.getByText('New physical event discovered', { exact: true }).waitFor();
  await page
    .locator('.incident-watch-timeline')
    .getByRole('button', {
      name: 'Focus Equatorial wildfire perimeter fixture on map',
    })
    .click();
  await page
    .locator('.map-overlay')
    .getByText(/0\.00,\s*-120\.00/)
    .waitFor();
  await page.getByRole('button', { name: 'Mark timeline read' }).click();
  await watchCard.getByText('0 unread', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Close operations', exact: true }).click();
  await page.getByRole('button', { name: 'Open assistant' }).click();
  await page.getByLabel('Question').fill('Zoom into Japan.');
  const mapActionResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/assistant'),
  );
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  if (!(await mapActionResponse).ok()) {
    throw new Error('The agent map-tool request failed.');
  }
  await page
    .locator('.message-assistant')
    .filter({ hasText: 'Showing Japan on the map.' })
    .waitFor();
  await page.getByText(/138\.00/).waitFor();
  await page
    .getByLabel('Question')
    .fill(
      'Please give me the latest information about the earthquake in Japan on August 5, 2026.',
    );
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  await page.getByText('Ishikawa, Japan', { exact: true }).waitFor({ timeout: 30_000 });
  await page.getByText(/37\.02,\s*137\.01/).waitFor();
  await page.getByRole('heading', { name: 'Situation summary' }).waitFor();
  await page.getByText('Buildings damaged: 4.').first().waitFor();
  await page.getByRole('link', { name: /Global situation fixture/ }).waitFor();
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
  console.log(
    'System test passed: all six Active Incidents hazards focused their own geometry, a scheduled Incident Watch refresh produced a visible source-backed timeline alert, and the existing assistant workflow rendered.',
  );
} finally {
  stopStack();
}
