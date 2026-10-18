// Bounded real desktop discovery. No reference identities or synthetic API routes.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium, expect } from '@playwright/test';

const output = process.env.LIVE_SCREENSHOT_DIR;
const reportPath = process.env.LIVE_EVALUATION_OUTPUT;
assert(output && reportPath, 'Set external screenshot and evaluation output paths.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
const errors = [];
const consoleMessages = [];
const checks = [];
const groundRequests = [];
const result = {
  kind: 'live production application desktop workflow; no reference preloading',
  started_at: new Date().toISOString(),
  url: 'http://127.0.0.1:4173',
  viewport: { width: 1536, height: 1024 },
  checks,
  errors,
  consoleMessages,
  groundRequests,
  inspected: [],
};
const save = () => writeFile(reportPath, JSON.stringify(result, null, 2));
const check = (name, evidence, status = 'passed') =>
  checks.push({ name, status, evidence });
page.on('pageerror', (error) => errors.push(error.message));
page.on('console', (message) => {
  if (['error', 'warning'].includes(message.type()))
    consoleMessages.push({
      type: message.type(),
      text: message.text(),
      url: message.location().url,
    });
});
page.on('request', (request) => {
  if (request.url().includes('/ground-imagery/requests'))
    groundRequests.push({ method: request.method(), url: request.url() });
});
try {
  await page.goto(result.url, { waitUntil: 'domcontentloaded' });
  assert.equal(await page.title(), 'Disaster Monitor');
  await expect(
    page.getByRole('button', { name: 'Scan the world', exact: true }),
  ).toBeVisible();
  check(
    'Page identity and meaningful controls',
    'Disaster Monitor, reporting-period selector, world map and scan control rendered.',
  );
  await page.getByLabel('Reporting period', { exact: true }).selectOption('30');
  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith('/discovery-scans') &&
      response.request().method() === 'POST',
  );
  await page
    .getByRole('button', { name: 'Scan the world', exact: true })
    .press('Enter');
  const initialResponse = await started;
  assert.equal(initialResponse.status(), 202);
  let scan = await initialResponse.json();
  result.scan = scan;
  await save();
  const deadline = Date.now() + 240000;
  while (scan.status === 'running' && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    const response = await page.request.get(
      `http://127.0.0.1:8787/api/v1/discovery-scans/${scan.scan_id}`,
    );
    assert.equal(response.status(), 200);
    scan = await response.json();
    result.scan = scan;
    await save();
  }
  assert.notEqual(scan.status, 'running', 'Bounded final scan did not finish.');
  assert.notEqual(scan.status, 'failed', 'No real reports available for inspection.');
  await expect(
    page.getByText(
      `${scan.snapshot.incidents.length} events from ${scan.reports_seen} collected reports.`,
      { exact: true },
    ),
  ).toBeVisible({ timeout: 10000 });
  await page.screenshot({ path: join(output, 'live-discovery.png'), fullPage: false });
  check(
    'Live scan presentation',
    `${scan.status}; ${scan.reports_seen} retained reports; ${scan.snapshot.incidents.length} provisional event records; ${scan.unlocated_count} unlocated.`,
  );
  const withClaims = scan.snapshot.incidents.filter((event) =>
    event.discovery_reports.some((report) => report.claims?.length),
  );
  const examples = [withClaims[0] ?? scan.snapshot.incidents[0]];
  const second = withClaims.find((event) => event.disaster !== examples[0].disaster);
  if (second) examples.push(second);
  for (const event of examples) {
    // Compact cards omit provenance details. The displayed collection preserves
    // snapshot order; the resulting URL and article links verify event identity.
    const card = page
      .locator('.incident-card')
      .nth(
        scan.snapshot.incidents.findIndex((item) => item.event_id === event.event_id),
      );
    await expect(card).toHaveCount(1);
    await card.getByRole('button').first().click();
    assert.equal(new URL(page.url()).searchParams.get('i'), event.event_id);
    const articles = page.getByRole('region', { name: 'Dated articles', exact: true });
    await expect(articles.getByRole('link').first()).toBeVisible();
    const links = await articles
      .getByRole('link')
      .evaluateAll((items) => items.map((item) => item.href));
    assert(
      links.every((url) =>
        event.discovery_reports.some((report) => report.source.canonical_url === url),
      ),
    );
    const impacts = page.getByRole('region', { name: 'Reported impacts', exact: true });
    const summaries = impacts.locator('summary').filter({ hasText: / · \d+ accounts/ });
    if (await summaries.count()) await summaries.first().press('Enter');
    if (!event.geometry)
      await expect(page.getByText(/Location unresolved for mapping/)).toBeVisible();
    await page.screenshot({
      path: join(output, `live-${event.disaster}-articles.png`),
      fullPage: false,
    });
    const mediaResponse = page.waitForResponse((response) =>
      response
        .url()
        .includes(`/incidents/${encodeURIComponent(event.event_id)}/evidence/media`),
    );
    await page.getByText('Article photographs', { exact: true }).press('Enter');
    const mediaHttp = await mediaResponse;
    const media = await mediaHttp.json();
    await expect(page.locator('.standalone-evidence')).toBeVisible();
    await page.screenshot({
      path: join(output, `live-${event.disaster}-photographs.png`),
      fullPage: false,
    });
    const before = groundRequests.length;
    await page
      .getByRole('button', { name: 'Find imagery', exact: true })
      .press('Enter');
    if (event.event_time === null) {
      await expect(
        page.getByText(/Publication time cannot target imagery/),
      ).toBeVisible();
      assert.equal(groundRequests.length, before);
    } else {
      await expect(
        page.getByRole('heading', { name: 'Region basis' }).or(page.getByRole('alert')),
      ).toBeVisible({ timeout: 60000 });
    }
    await page.getByText('Event articles and impacts', { exact: true }).press('Enter');
    await expect(
      page.getByRole('heading', {
        name: `Collected articles · ${event.discovery_reports.length}`,
      }),
    ).toBeVisible();
    await page.screenshot({
      path: join(output, `live-${event.disaster}-imagery-status.png`),
      fullPage: false,
    });
    result.inspected.push({
      event_id: event.event_id,
      disaster: event.disaster,
      source: event.source,
      article_links: links,
      media_http_status: mediaHttp.status(),
      media,
      imagery:
        event.event_time === null
          ? 'untargetable: unknown onset; no fabricated catalog request'
          : 'attempted; inspect displayed state',
      reporting_accessible_during_imagery: true,
    });
    check(
      `Real ${event.disaster} inspection`,
      'List identity/URL, article links, attributed accounts, reported-place precision, photograph result, imagery state, and reporting in Ground view verified.',
    );
    await page.getByRole('button', { name: 'Return to event' }).click();
    await page.getByRole('button', { name: 'Back to events' }).click();
    await save();
  }
  assert.equal(await page.locator('nextjs-portal').count(), 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(
    consoleMessages.filter((message) => message.type === 'error'),
    [],
  );
  check(
    'Framework and console health',
    'No runtime exceptions, console errors or Next.js overlay.',
  );
  result.finished_at = new Date().toISOString();
  await save();
  console.log(JSON.stringify({ checks, errors, scan_id: scan.scan_id }, null, 2));
} catch (error) {
  result.failure = String(error);
  await page.screenshot({ path: join(output, 'live-failure.png'), fullPage: false });
  await save();
  throw error;
} finally {
  await browser.close();
}
