export async function exerciseResponsiveWorkspaces(page) {
  await page.setViewportSize({ width: 320, height: 740 });
  for (const name of ['Explore', 'Saved', 'Sources', 'Tools']) {
    await assertFitsViewport(
      page,
      page
        .getByRole('navigation', { name: 'Primary navigation' })
        .getByRole('button', { name, exact: true }),
      name,
    );
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of ['Search commands', 'Open help', 'Ask a question']) {
    const control = page.getByRole('button', { name, exact: true });
    await assertFitsViewport(page, control, name);
    if (
      await control.evaluate((element) => element.scrollWidth > element.clientWidth)
    ) {
      throw new Error(`${name} content overlaps neighboring header controls.`);
    }
  }
  const navigation = page.getByRole('navigation', { name: 'Primary navigation' });
  for (const name of ['Explore', 'Saved', 'Sources', 'Tools']) {
    await assertFitsViewport(
      page,
      navigation.getByRole('button', { name, exact: true }),
      name,
    );
  }
  await navigation.getByRole('button', { name: 'Sources', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search sources' }).waitFor();
  for (const label of ['Search sources', 'Hazard', 'Role']) {
    await assertFitsViewport(page, page.getByLabel(label, { exact: true }), label);
  }
  if (process.env.SYSTEM_TEST_SOURCES_SCREENSHOT) {
    await page.screenshot({
      path: process.env.SYSTEM_TEST_SOURCES_SCREENSHOT,
      fullPage: false,
    });
  }
  await page.setViewportSize({ width: 1536, height: 1024 });
  const sourcesOverflow = await page
    .getByRole('complementary', { name: 'Source Catalog' })
    .locator('.source-catalog-scroll')
    .evaluate((element) => element.scrollWidth > element.clientWidth);
  if (sourcesOverflow) {
    throw new Error('Source filters overflow the desktop source directory.');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await navigation.getByRole('button', { name: 'Explore', exact: true }).click();
  const map = page.getByLabel('Interactive map', { exact: true });
  const box = await map.boundingBox();
  if (!box || box.width < 300)
    throw new Error('The mobile map was reduced to a clipped sliver.');
  await page.getByRole('button', { name: 'Search commands', exact: true }).click();
  await page.getByRole('dialog', { name: 'Command palette' }).waitFor();
  await page.getByRole('button', { name: 'Close command palette' }).click();
  await page.getByRole('button', { name: 'Open help' }).click();
  await page.getByRole('dialog', { name: 'How to use Disaster Monitor' }).waitFor();
  await page.getByRole('button', { name: 'Close help guide' }).click();
  await page.getByRole('button', { name: 'Ask a question' }).click();
  await page
    .getByRole('complementary', { name: 'Disaster Monitor assistant' })
    .waitFor();
  await page.getByRole('button', { name: 'Close assistant' }).click();
  await page.setViewportSize({ width: 1536, height: 1024 });
}

async function assertFitsViewport(page, locator, label) {
  const box = await locator.boundingBox();
  const width = page.viewportSize().width;
  if (!box || box.x < 0 || box.x + box.width > width + 1) {
    throw new Error(`${label} is clipped outside the ${width}px viewport.`);
  }
}
