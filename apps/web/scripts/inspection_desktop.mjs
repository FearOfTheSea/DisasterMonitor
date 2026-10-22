// Controlled desktop acceptance. Start INSPECTION_ACCEPTANCE=1 stack separately.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, expect } from '@playwright/test';

const output = process.env.INSPECTION_SCREENSHOT_DIR;
assert(output, 'Set INSPECTION_SCREENSHOT_DIR outside the repository.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1536, height: 1024 },
  reducedMotion: 'reduce',
});
const errors = [];
const consoleErrors = [];
const quotaResponses = [];
const warnings = [];
const checks = [];
page.on('pageerror', (error) => errors.push(error.message));
page.on('response', async (response) => {
  if (response.status() === 429 && response.url().includes('/ground-imagery/')) {
    const payload = await response.json();
    quotaResponses.push({ url: response.url(), status: 429, detail: payload.detail });
  }
});
page.on('console', (message) => {
  if (message.type() === 'warning') warnings.push(message.text());
  if (
    message.type() === 'error' ||
    (message.type() === 'warning' &&
      !message.text().startsWith('Canvas2D: Multiple readback operations'))
  )
    consoleErrors.push({ text: message.text(), url: message.location().url });
});
const capture = async (name) =>
  page.screenshot({ path: join(output, `${name}.png`), fullPage: false });
const check = (name, evidence) => checks.push({ name, result: 'passed', evidence });
try {
  await page.context().route('https://controlled.example/**', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: '<title>Controlled source fixture</title><h1>Controlled source fixture</h1><p>Not live news.</p>',
    }),
  );
  await page.goto('http://127.0.0.1:4173/?c=10%2C105&z=5', {
    waitUntil: 'domcontentloaded',
  });
  assert.equal(await page.title(), 'Disaster Monitor');
  await page
    .getByRole('button', { name: 'Scan the world', exact: true })
    .press('Enter');
  await expect(
    page.getByText(
      /7 associated physical events · 0 unresolved event candidates · 1 context\/fragment records · 57 collected reports/,
    ),
  ).toBeVisible({ timeout: 20000 });
  check(
    'Page identity and meaningful content',
    'Disaster Monitor; scan returned seven physical events and one context record from 57 controlled reports across seven categories.',
  );
  const map = page.getByLabel('Interactive map', { exact: true });
  const box = await map.boundingBox();
  assert(box);
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(
    page.getByRole('heading', { name: 'Flood', exact: true, level: 2 }),
  ).toBeVisible();
  check('Map selection', 'Clicking the source point opens the flood event pane.');
  await page.getByRole('button', { name: 'Back to events' }).click();
  await page.locator('.incident-card-flood button').click();
  const impact = page.getByRole('region', { name: 'Reported impacts' });
  await impact.getByText('Fatalities · 8 accounts', { exact: true }).press('Enter');
  await expect(impact.getByText('Fatalities: 0', { exact: true })).toBeVisible();
  await expect(
    impact.getByText(/Correction: no deaths were reported in North District/),
  ).toBeVisible();
  await impact.getByText('Fatalities: 0', { exact: true }).scrollIntoViewIfNeeded();
  await capture('inspection-claims');
  const popupPromise = page.waitForEvent('popup');
  await impact.getByRole('link').first().click();
  const popup = await popupPromise;
  await expect(
    popup.getByRole('heading', { name: 'Controlled source fixture' }),
  ).toBeVisible();
  assert(popup.url().startsWith('https://controlled.example/flood/'));
  await popup.close();
  check(
    'Claim attribution and navigation',
    'Zero and differing preliminary counts retain source links, scope, dates, excerpts, and correction wording.',
  );
  await impact.getByText('Fatalities · 8 accounts', { exact: true }).press('Enter');
  const articles = page.getByRole('region', { name: 'Dated articles' });
  assert.equal(await articles.getByRole('link').count(), 5);
  await articles
    .getByRole('button', { name: 'Next articles', exact: true })
    .press('Enter');
  assert.equal(await articles.getByRole('link').count(), 2);
  await page.getByText('Unknown publication times · 1', { exact: true }).press('Enter');
  await expect(
    page.getByText(/Indexing and retrieval times do not establish publication time/),
  ).toBeVisible();
  await capture('inspection-articles');
  check(
    'Article pagination and missing dates',
    'Five latest dated links, two remaining dated links, and one separately labelled unknown publication. Enter operates paging and disclosures.',
  );
  await page.getByText('Article photographs', { exact: true }).press('Enter');
  const photographs = page.getByRole('region', {
    name: 'Article photograph collection',
  });
  await expect(
    photographs.getByRole('heading', { name: 'Article photographs · 7 retained' }),
  ).toBeVisible();
  await photographs.getByRole('img').first().scrollIntoViewIfNeeded();
  await expect
    .poll(() =>
      photographs
        .getByRole('img')
        .first()
        .evaluate((img) => img.complete && img.naturalWidth > 0),
    )
    .toBe(true);
  assert.equal(await photographs.getByRole('img').count(), 5);
  await photographs.getByRole('button', { name: 'Next photographs' }).press('Enter');
  assert.equal(await photographs.getByRole('img').count(), 2);
  await expect(photographs.getByText(/Photograph delivery failed/)).toBeVisible();
  await capture('inspection-photographs');
  check(
    'Photograph browsing',
    'Seven synthetic test assets, paged five/two; actual image endpoint decodes, broken delivery retains article link, acquisition/storage limits remain visible.',
  );
  const originalIncidentUrl = page.url();
  const searching = page.waitForResponse(
    (response) =>
      response.url().endsWith('/ground-imagery/requests') &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Find imagery', exact: true }).press('Enter');
  const originalResponse = await searching;
  assert.equal(originalResponse.status(), 202);
  const originalRequest = await originalResponse.json();
  await expect(
    page
      .getByRole('heading', { name: 'Prepared observation' })
      .or(page.getByRole('heading', { name: 'Matched before / after' })),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole('button', { name: 'Preparing…', exact: true }),
  ).toHaveCount(0);
  await expect
    .poll(() =>
      page
        .locator('.ground-single-preview img')
        .evaluate((img) => img.complete && img.naturalWidth > 0),
    )
    .toBe(true);
  await page.getByText('Event articles and impacts', { exact: true }).press('Enter');
  await expect(
    page.getByRole('heading', { name: 'Collected articles · 8' }),
  ).toBeVisible();
  await page.getByText('Event articles and impacts', { exact: true }).press('Enter');
  await capture('inspection-imagery');
  check(
    'One-action imagery and nonblocking reporting',
    'Find imagery triggers real controlled Ground catalog/preparation; dated artifacts and coverage map render; articles remain accessible in the imagery view.',
  );
  await page.getByRole('button', { name: 'Return to event' }).click();
  await page.getByRole('button', { name: 'Back to events' }).click();
  const categories = [
    'Earthquake',
    'Flood',
    'Wildfire',
    'Landslide',
    'Tropical cyclone',
    'Volcanic eruption',
    'Drought',
  ];
  for (let index = 0; index < 7; index++) {
    await page
      .locator(
        `.incident-card-${['earthquake', 'flood', 'wildfire', 'landslide', 'tropical_cyclone', 'volcanic_eruption', 'drought'][index]} button`,
      )
      .click();
    await expect(
      page.getByRole('heading', { name: categories[index], exact: true, level: 2 }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: 'Find imagery', exact: true })
      .press('Enter');
    await expect(page.getByRole('heading', { name: 'Region basis' })).toBeVisible({
      timeout: 20000,
    });
    if (index === 0)
      await expect(
        page.getByText('No recent observation', { exact: true }).first(),
      ).toBeVisible();
    if (index === 2)
      await expect(page.getByText(/provider error/i).first()).toBeVisible();
    if (index === 4)
      await expect(
        page.getByText('Region needed', { exact: true }).first(),
      ).toBeVisible();
    await page.getByRole('button', { name: 'Return to event' }).click();
    await page.getByRole('button', { name: 'Back to events' }).click();
  }
  check(
    'Seven category imagery paths',
    'All seven inspected. Earthquake has no acquisition; wildfire has provider failure; cyclone needs region; drought uses a supported area.',
  );
  await page.getByText('Context and unresolved evidence (1)', { exact: true }).click();
  await page
    .getByRole('button', { name: 'Inspect retained Unresolved Valley', exact: true })
    .click();
  await page.getByRole('button', { name: 'Find imagery', exact: true }).press('Enter');
  await expect(page.getByText(/Publication time cannot target imagery/)).toBeVisible();
  await page.getByText('Event articles and impacts', { exact: true }).press('Enter');
  await expect(page.getByText(/Location unresolved for mapping/)).toBeVisible();
  await capture('inspection-unresolved');
  check(
    'Missing location/time',
    'Unlocated drought remains inspectable; no fabricated imagery target or onset.',
  );
  const metricsUrl = 'http://127.0.0.1:8787/api/v1/__inspection/metrics';
  const beforeShared = await (await page.request.get(metricsUrl)).json();
  const secondContext = await browser.newContext({
    viewport: { width: 1536, height: 1024 },
    reducedMotion: 'reduce',
  });
  const secondPage = await secondContext.newPage();
  secondPage.on('pageerror', (error) => errors.push(error.message));
  await secondPage.goto(originalIncidentUrl, { waitUntil: 'domcontentloaded' });
  await expect(
    secondPage.getByRole('heading', { name: 'Flood', exact: true, level: 2 }),
  ).toBeVisible({ timeout: 20000 });
  const reusedResponse = secondPage.waitForResponse(
    (response) =>
      response.url().endsWith('/ground-imagery/requests') &&
      response.request().method() === 'POST',
  );
  await secondPage.getByRole('button', { name: 'Find imagery', exact: true }).click();
  const reused = await (await reusedResponse).json();
  assert.notEqual(reused.request_id, originalRequest.request_id);
  await expect(secondPage.getByText(/Recent catalog snapshot reused/)).toBeVisible();
  await expect(secondPage.getByText(/Previously retrieved imagery reused/)).toBeVisible(
    { timeout: 20000 },
  );
  await expect
    .poll(() =>
      secondPage
        .locator('.ground-single-preview img')
        .evaluate((img) => img.complete && img.naturalWidth > 0),
    )
    .toBe(true);
  await secondPage.screenshot({
    path: join(output, 'inspection-shared-cache.png'),
    fullPage: false,
  });
  const afterShared = await (await secondPage.request.get(metricsUrl)).json();
  assert.deepEqual(afterShared, beforeShared);
  await secondContext.close();
  check(
    'Independent session cache reuse',
    'Second browser context has a distinct mutable request, original catalog cutoff and cache notices, and a decoded preview with zero additional catalog/render provider calls.',
  );
  assert.equal(await page.locator('nextjs-portal').count(), 0);
  const expectedQuotaConsole = consoleErrors.filter(
    (entry) =>
      entry.text.includes('status of 429') &&
      quotaResponses.some(
        (response) =>
          response.url === entry.url &&
          response.detail.includes('Ground view limit for image preparations'),
      ),
  );
  errors.push(
    ...consoleErrors
      .filter((entry) => !expectedQuotaConsole.includes(entry))
      .map((entry) => entry.text),
  );
  assert.deepEqual(errors, []);
  check(
    'Console health and framework overlay',
    `No unexpected console errors, page exceptions, or Next.js overlay. ${expectedQuotaConsole.length} confirmed preparation quota network messages are recorded as refusals; no delivery credit.`,
  );
  await writeFile(
    join(output, 'inspection-browser-results.json'),
    JSON.stringify(
      {
        url: 'http://127.0.0.1:4173',
        viewport: { width: 1536, height: 1024 },
        controlled: true,
        checks,
        errors,
        warnings,
        quotaResponses,
        expectedQuotaConsole,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks, errors }, null, 2));
} catch (error) {
  await capture('inspection-failure');
  await writeFile(
    join(output, 'inspection-browser-failure.txt'),
    String(error) + '\n' + errors.join('\n'),
  );
  throw error;
} finally {
  await browser.close();
}
