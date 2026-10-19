/** Exercise real layout and input; a DOM-only component test cannot detect clipping. */
export async function exerciseDesktopIncidentAccess(page, eventButtonName) {
  for (const viewport of [
    { width: 714, height: 676 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    const actual = await page.locator('html').evaluate((element) => ({
      width: element.clientWidth,
      height: element.clientHeight,
    }));
    if (actual.width !== viewport.width || actual.height !== viewport.height) {
      throw new Error(`Requested viewport was not applied: ${JSON.stringify(actual)}.`);
    }
    const listHeight = await page
      .locator('.active-incidents-scroll')
      .evaluate((element) => element.clientHeight);
    if (listHeight < 1) {
      throw new Error(
        `Event list has no height at ${viewport.width}×${viewport.height}.`,
      );
    }
    const eventButton = page.getByRole('button', { name: eventButtonName });
    await eventButton.click();
    await page
      .getByRole('button', { name: /Back to events$/ })
      .waitFor({ state: 'visible' });
    await page.getByRole('button', { name: /Back to events$/ }).click();
    await eventButton.press('Enter');
    await page
      .getByRole('button', { name: /Back to events$/ })
      .waitFor({ state: 'visible' });
    await page.getByRole('button', { name: /Back to events$/ }).click();
  }
}
